\

# Flutter Integration Guide: Workout Recommendations

This guide explains how to integrate the deployed Python recommendation engine API into the HeronFit Flutter application.

**Goal:** Fetch personalized workout template recommendations from the backend API and display them to the user.

**API Endpoint:** `https://heronfit-recommendation-service.onrender.com/recommendations/workout/{user_id}`
**Method:** `GET`
**Response:** JSON object containing a list of recommended workout templates.

```json
// Example Response Structure
{
  "recommendations": [
    {
      "template_name": "Recommended Pull Day",
      "focus": "Back, Biceps",
      "exercises": [
        "exercise_id_1",
        "exercise_id_2"
        // ...
      ]
    }
    // ... more templates
  ]
}
```

## Prerequisites

1.  **`http` Package:** Ensure the `http` package is added to your `pubspec.yaml`:
    ```yaml
    dependencies:
      flutter:
        sdk: flutter
      http: ^1.2.1 # Or latest version
      # ... other dependencies
    ```
    Run `flutter pub get` if you add it.
2.  **API URL:** The deployed URL is `https://heronfit-recommendation-service.onrender.com`.
3.  **User ID:** You need access to the currently logged-in user's Supabase ID within the Flutter app (likely available via your `AuthController` or `UserProvider`).

## Implementation Steps

### 1. Define Data Models

Ensure you have Dart models to represent the data received from the API and your Supabase tables.

**(Create/Verify `lib/models/workout_template_model.dart`)**

```dart
// lib/models/workout_template_model.dart
import 'package:flutter/foundation.dart';

class WorkoutTemplate {
  final String templateName;
  final String focus;
  final List<String> exerciseIds; // List of exercise UUIDs

  WorkoutTemplate({
    required this.templateName,
    required this.focus,
    required this.exerciseIds,
  });

  factory WorkoutTemplate.fromJson(Map<String, dynamic> json) {
    return WorkoutTemplate(
      templateName: json['template_name'] as String? ?? 'Unnamed Template',
      focus: json['focus'] as String? ?? 'General Focus',
      exerciseIds: (json['exercises'] as List<dynamic>?)
              ?.map((e) => e.toString())
              ?.toList() ??
          [],
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'template_name': templateName,
      'focus': focus,
      'exercises': exerciseIds,
    };
  }
}
```

**(Create/Verify `lib/models/exercise_model.dart`)**
_(This should match the structure of your Supabase `exercises` table)_

```dart
// lib/models/exercise_model.dart (Example - Adapt to your exact schema)
class Exercise {
  final String id;
  final String name;
  final List<String> primaryMuscles;
  final String? equipment;
  final String? level;
  final String? category;
  // Add other fields like instructions, images, etc.

  Exercise({
    required this.id,
    required this.name,
    required this.primaryMuscles,
    this.equipment,
    this.level,
    this.category,
    // ... other fields
  });

  factory Exercise.fromJson(Map<String, dynamic> json) {
    return Exercise(
      id: json['id'] as String,
      name: json['name'] as String? ?? 'Unknown Exercise',
      primaryMuscles: (json['primaryMuscles'] as List<dynamic>?)
              ?.map((e) => e.toString())
              ?.toList() ??
          [],
      equipment: json['equipment'] as String?,
      level: json['level'] as String?,
      category: json['category'] as String?,
      // ... parse other fields
    );
  }
}
```

### 2. Create Recommendation Service

Create a service class to handle communication with the recommendation API.

**(Create `lib/core/services/recommendation_service.dart`)**

```dart
// lib/core/services/recommendation_service.dart
import 'dart:convert';
import 'package:http/http.dart' as http;
// Adjust import path based on your project structure
import 'package:heronfit/models/workout_template_model.dart';

class RecommendationService {
  // Use the deployed Render URL
  final String _baseUrl = "https://heronfit-recommendation-service.onrender.com";

  Future<List<WorkoutTemplate>> getWorkoutRecommendations(String userId) async {
    final url = Uri.parse('$_baseUrl/recommendations/workout/$userId');
    print('Calling recommendation API: $url'); // Debugging

    try {
      final response = await http.get(
        url,
        headers: {'Content-Type': 'application/json'},
      ).timeout(const Duration(seconds: 20)); // Increased timeout for potentially cold starts

      print('API Response Status: ${response.statusCode}'); // Debugging

      if (response.statusCode == 200) {
        final Map<String, dynamic> data = json.decode(response.body);

        if (data.containsKey('recommendations') && data['recommendations'] is List) {
           final List<dynamic> recommendationsJson = data['recommendations'];
           if (recommendationsJson.isEmpty) {
             print('API returned empty recommendations list.');
             return [];
           }
           return recommendationsJson
              .map((jsonItem) => WorkoutTemplate.fromJson(jsonItem as Map<String, dynamic>))
              .toList();
        } else {
           print('API response missing or invalid "recommendations" key.');
           return []; // Or throw an exception
        }
      } else {
        print('Error fetching recommendations: ${response.statusCode} - ${response.body}');
        throw Exception('Failed to load recommendations. Status code: ${response.statusCode}');
      }
    } catch (e) {
      print('Error calling recommendation API: $e');
      throw Exception('Failed to connect or parse recommendations: $e');
    }
  }
}
```

### 3. Integrate with Controller

Use a controller (like your existing `WorkoutController` or create a new one) to manage fetching recommendations and related state (loading, error, data).

**(Modify/Verify `lib/controllers/workout_controller.dart`)**
_(Assuming you use Provider/ChangeNotifier, adapt if using Riverpod, GetX, etc.)_

```dart
// lib/controllers/workout_controller.dart (Conceptual Example)
import 'package:flutter/material.dart';
import 'package:heronfit/core/services/recommendation_service.dart';
import 'package:heronfit/models/workout_template_model.dart';
import 'package:heronfit/models/exercise_model.dart';
import 'package:heronfit/core/services/supabase_service.dart'; // Ensure this exists and is correct

class WorkoutController with ChangeNotifier {
  final RecommendationService _recommendationService = RecommendationService();
  // Assuming you have SupabaseService for fetching exercise details
  final SupabaseService _supabaseService = SupabaseService();

  List<WorkoutTemplate> _recommendedTemplates = [];
  List<WorkoutTemplate> get recommendedTemplates => _recommendedTemplates;

  Map<String, Exercise> _fetchedExerciseDetails = {}; // Cache
  Map<String, Exercise> get fetchedExerciseDetails => _fetchedExerciseDetails;

  bool _isLoadingRecommendations = false;
  bool get isLoadingRecommendations => _isLoadingRecommendations;

  bool _isLoadingDetails = false;
  bool get isLoadingDetails => _isLoadingDetails;

  String? _errorMessage;
  String? get errorMessage => _errorMessage;

  // Call this to fetch recommendations
  Future<void> fetchRecommendations(String userId) async {
    if (_isLoadingRecommendations) return;
    _isLoadingRecommendations = true;
    _errorMessage = null;
    notifyListeners();

    try {
      _recommendedTemplates = await _recommendationService.getWorkoutRecommendations(userId);
      print('Fetched ${_recommendedTemplates.length} recommendations.');
    } catch (e) {
      print('Error in controller fetching recommendations: $e');
      _errorMessage = "Failed to load recommendations. Check connection.";
      _recommendedTemplates = [];
    } finally {
      _isLoadingRecommendations = false;
      notifyListeners();
    }
  }

  // Call this when a template is selected
  Future<void> fetchExerciseDetailsForTemplate(WorkoutTemplate template) async {
     if (_isLoadingDetails) return;
     final idsToFetch = template.exerciseIds
         .where((id) => !_fetchedExerciseDetails.containsKey(id))
         .toList();
     if (idsToFetch.isEmpty) return;

     _isLoadingDetails = true;
     _errorMessage = null;
     notifyListeners();

     try {
       // Ensure SupabaseService has getExercisesByIds
       final exercises = await _supabaseService.getExercisesByIds(idsToFetch);
       for (var exercise in exercises) {
         _fetchedExerciseDetails[exercise.id] = exercise;
       }
       print('Fetched details for ${exercises.length} exercises.');
     } catch (e) {
       print('Error fetching exercise details: $e');
       _errorMessage = "Failed to load exercise details.";
     } finally {
       _isLoadingDetails = false;
       notifyListeners();
     }
  }

  Exercise? getExerciseDetails(String exerciseId) {
      return _fetchedExerciseDetails[exerciseId];
  }
}

// Remember to provide WorkoutController in your widget tree (e.g., main.dart)
// MultiProvider(
//   providers: [
//     // ... other providers
//     ChangeNotifierProvider(create: (_) => WorkoutController()),
//   ],
//   child: MyApp(),
// )
```

### 4. Display Recommendations in UI

Modify a relevant screen (e.g., `lib/views/home/home_screen.dart` or `lib/views/workout/workout_screen.dart`) to display the fetched recommendations.

**(Example Usage in a Screen - e.g., `HomeScreen`)**

```dart
// lib/views/home/home_screen.dart (or relevant screen)
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:heronfit/controllers/workout_controller.dart';
import 'package:heronfit/models/workout_template_model.dart';
// Import your AuthController/UserProvider to get the user ID
// import 'package:heronfit/providers/user_provider.dart';
// Import the card widget if you create one
// import 'package:heronfit/widgets/recommended_workout_card.dart';

class HomeScreen extends StatefulWidget {
  // ... constructor ...
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  @override
  void initState() {
    super.initState();
    // Fetch recommendations after the first frame
    WidgetsBinding.instance.addPostFrameCallback((_) {
      // --- GET USER ID ---
      // Replace this with your actual logic to get the logged-in user's ID
      // Example: final userId = Provider.of<UserProvider>(context, listen: false).user?.id;
      final String? userId = "REPLACE_WITH_ACTUAL_USER_ID_LOGIC";

      if (userId != null && userId.isNotEmpty) {
        Provider.of<WorkoutController>(context, listen: false).fetchRecommendations(userId);
      } else {
        print("User ID not available, cannot fetch recommendations.");
        // Optionally set an error state in the controller
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    // ... your existing Scaffold and other widgets ...

    return Scaffold(
      // ... AppBar etc ...
      body: SingleChildScrollView( // Or use CustomScrollView with Slivers
        child: Column(
          children: [
            // ... Your existing WelcomeHeader, ActivityCard etc. ...

            // --- Recommendation Section ---
            Padding(
              padding: const EdgeInsets.all(16.0),
              child: Consumer<WorkoutController>(
                builder: (context, controller, child) {
                  if (controller.isLoadingRecommendations) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (controller.errorMessage != null && controller.recommendedTemplates.isEmpty) {
                    return Center(child: Text('Could not load recommendations: ${controller.errorMessage}'));
                  }
                  if (controller.recommendedTemplates.isEmpty) {
                    return const Center(child: Text('No recommendations available right now.'));
                  }

                  // Display the list
                  return Column(
                     crossAxisAlignment: CrossAxisAlignment.start,
                     children: [
                        Text("Try these Workouts", style: Theme.of(context).textTheme.headlineSmall),
                        const SizedBox(height: 10),
                        ListView.builder(
                           shrinkWrap: true, // Important inside SingleChildScrollView/Column
                           physics: const NeverScrollableScrollPhysics(), // Disable ListView scrolling
                           itemCount: controller.recommendedTemplates.length,
                           itemBuilder: (context, index) {
                              final template = controller.recommendedTemplates[index];
                              // Use a dedicated card widget for better structure
                              return RecommendedWorkoutCard( // Assumes you create this widget
                                 template: template,
                                 onTap: () {
                                    // Handle tap: Navigate or show details
                                    _showExerciseListDialog(context, template);
                                 },
                              );
                           },
                        ),
                     ],
                  );
                },
              ),
            ),
            // ... rest of your home screen content ...
          ],
        ),
      ),
    );
  }

  // Example Dialog function (needs RecommendedWorkoutCard widget below)
  void _showExerciseListDialog(BuildContext context, WorkoutTemplate template) async {
     final controller = Provider.of<WorkoutController>(context, listen: false);
     await controller.fetchExerciseDetailsForTemplate(template); // Fetch details on demand

     showDialog(
        context: context,
        builder: (BuildContext context) {
          return Consumer<WorkoutController>( // Use Consumer to react to detail loading state
             builder: (context, detailController, child) {
                return AlertDialog(
                   title: Text(template.templateName),
                   content: SingleChildScrollView(
                      child: ListBody(
                         children: detailController.isLoadingDetails
                            ? [const Center(child: CircularProgressIndicator())]
                            : template.exerciseIds.map((id) {
                                final exercise = detailController.getExerciseDetails(id);
                                return ListTile(
                                   title: Text(exercise?.name ?? 'Loading...'),
                                   subtitle: Text(exercise?.primaryMuscles.join(', ') ?? ''),
                                );
                             }).toList(),
                      ),
                   ),
                   actions: <Widget>[
                      TextButton(
                         child: const Text('Close'),
                         onPressed: () => Navigator.of(context).pop(),
                      ),
                      TextButton(
                         child: const Text('Start Workout'),
                         onPressed: detailController.isLoadingDetails ? null : () { // Disable if loading
                            // TODO: Implement logic to start this workout
                            Navigator.of(context).pop();
                            print("Starting workout: ${template.templateName}");
                         },
                      ),
                   ],
                );
             },
          );
        },
     );
  }
}

// --- RecommendedWorkoutCard Widget ---
// (Create this in lib/widgets/ or similar)
class RecommendedWorkoutCard extends StatelessWidget {
  final WorkoutTemplate template;
  final VoidCallback onTap;

  const RecommendedWorkoutCard({
    Key? key,
    required this.template,
    required this.onTap,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 8.0),
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(template.templateName, style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 4),
              Text("Focus: ${template.focus}", style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 8),
              Text("${template.exerciseIds.length} exercises"),
            ],
          ),
        ),
      ),
    );
  }
}
```

### 5. Ensure Supabase Service Fetches Details

Make sure your `lib/core/services/supabase_service.dart` has the `getExercisesByIds` method (or similar) used by the `WorkoutController`.

**(Verify `lib/core/services/supabase_service.dart`)**

```dart
// lib/core/services/supabase_service.dart
import 'package:supabase_flutter/supabase_flutter.dart';
// Adjust import path
import 'package:heronfit/models/exercise_model.dart';

class SupabaseService {
  final SupabaseClient _client = Supabase.instance.client;

  // ... other methods ...

  Future<List<Exercise>> getExercisesByIds(List<String> ids) async {
    if (ids.isEmpty) return [];
    try {
      // Use postgrest syntax for selecting specific columns if needed
      final response = await _client
          .from('exercises')
          .select() // Fetch all columns for now
          .in_('id', ids)
          .execute();

      if (response.error != null) {
        print('Supabase error fetching exercises: ${response.error!.message}');
        throw Exception('Failed to fetch exercises: ${response.error!.message}');
      }
      final List<dynamic> data = response.data as List<dynamic>? ?? [];
      return data.map((json) => Exercise.fromJson(json as Map<String, dynamic>)).toList();
    } catch (e) {
      print('Exception fetching exercises by IDs: $e');
      throw Exception('An error occurred while fetching exercise details.');
    }
  }
}
```

## Testing Steps

1.  **Run the Flutter App:** Launch your app on an emulator or physical device.
2.  **Log In:** Ensure you are logged in with a user account that exists in your Supabase `users` table (ideally one with some workout history).
3.  **Navigate:** Go to the screen where you implemented the recommendation display (e.g., Home Screen).
4.  **Check Logs:** Look at your Flutter console logs. You should see:
    - `Calling recommendation API: https://heronfit-recommendation-service.onrender.com/recommendations/workout/YOUR_USER_ID`
    - `API Response Status: 200` (hopefully!)
    - `Fetched X recommendations.` (from the controller)
5.  **Verify UI:**
    - Check if a loading indicator appears briefly.
    - See if the "Try these Workouts" section appears with the recommended workout cards.
    - If there's an error, check if the error message is displayed.
6.  **Test Interaction:**
    - Tap on a recommended workout card.
    - Check the logs again. You should see logs related to fetching exercise details from Supabase.
    - Verify that the dialog appears, showing the list of exercises for that template (after a brief loading state for details if needed).
    - Check if the exercise names and muscle groups are displayed correctly.
7.  **Troubleshooting:**
    - **Connection Errors:** Double-check your device/emulator has internet access. Ensure the Render service URL is correct and the service is running. Check Render logs if requests aren't reaching it.
    - **Incorrect User ID:** Make sure the `userId` being passed to `fetchRecommendations` is the correct Supabase Auth User ID.
    - **Parsing Errors:** If you get errors related to JSON parsing, ensure your Dart models (`WorkoutTemplate`, `Exercise`) exactly match the structure returned by the API and your Supabase table, respectively. Pay attention to data types (e.g., `List<String>` vs `List<dynamic>`).
    - **Supabase Errors:** Check `getExercisesByIds` for any errors reported by Supabase (permissions, incorrect table/column names).
