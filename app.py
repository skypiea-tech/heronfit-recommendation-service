import os
import pandas as pd  # Add pandas import
from collections import Counter  # Add Counter import
import random  # Add random import
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Initialize Supabase client
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_SERVICE_KEY")

if not url or not key:
    raise ValueError("Supabase URL and Key must be set in the .env file")

supabase: Client = create_client(url, key)

@app.route('/')
def home():
    return "HeronFit Recommendation Engine is running!"

# --- Data Fetching Functions ---
def fetch_all_exercises():
    """Fetches all exercises from the Supabase 'exercises' table."""
    try:
        response = supabase.table('exercises').select('id, name, primaryMuscles, equipment, category, level').execute()
        if response.data:
            return pd.DataFrame(response.data)
        else:
            print("No exercises found or error fetching exercises.")
            return pd.DataFrame()
    except Exception as e:
        print(f"Error fetching exercises: {e}")
        return pd.DataFrame()

def fetch_user_history(user_id):
    """Fetches workout history for a given user_id, focusing on exercises done."""
    try:
        workouts_response = supabase.table('workouts').select('id').eq('user_id', user_id).execute()
        if not workouts_response.data:
            print(f"No workouts found for user_id: {user_id}")
            return pd.DataFrame(), pd.DataFrame()

        workout_ids = [w['id'] for w in workouts_response.data]
        if not workout_ids:
            print(f"No workout IDs found for user_id: {user_id}")
            return pd.DataFrame(), pd.DataFrame()

        workout_exercises_response = supabase.table('workout_exercises').select('exercise_id, workout_id').in_('workout_id', workout_ids).execute()
        if not workout_exercises_response.data:
            print(f"No workout exercises found for user_id: {user_id}")
            return pd.DataFrame(), pd.DataFrame()

        exercise_ids = list(set([we['exercise_id'] for we in workout_exercises_response.data if we.get('exercise_id')]))
        if not exercise_ids:
            print(f"No valid exercise IDs found in history for user_id: {user_id}")
            return pd.DataFrame(workout_exercises_response.data), pd.DataFrame()

        exercises_details_response = supabase.table('exercises').select('id, name, primaryMuscles').in_('id', exercise_ids).execute()
        if not exercises_details_response.data:
            print(f"Could not fetch details for exercises: {exercise_ids}")
            return pd.DataFrame(workout_exercises_response.data), pd.DataFrame()

        return pd.DataFrame(workout_exercises_response.data), pd.DataFrame(exercises_details_response.data)

    except Exception as e:
        print(f"Error fetching user history for user_id {user_id}: {e}")
        return pd.DataFrame(), pd.DataFrame()

# --- Workout Template Generation Logic ---
def _select_exercises_for_groups(target_groups, available_exercises, user_done_exercise_ids, num_exercises_target):
    """Helper function to select exercises based on target muscle groups."""
    selected_exercises = []
    selected_ids = set()

    # Helper to check if an exercise targets a group
    def targets_group(exercise_muscles, group_name):
        if not exercise_muscles: return False
        if isinstance(exercise_muscles, list):
            return any(group_name.lower() in m.lower() for m in exercise_muscles)
        elif isinstance(exercise_muscles, str):
            return group_name.lower() in exercise_muscles.lower()
        return False

    # Try to pick exercises for each target group
    for group, count in target_groups.items():
        group_exercises = available_exercises[
            available_exercises['primaryMuscles'].apply(lambda m: targets_group(m, group))
        ]
        group_exercises = group_exercises[~group_exercises['id'].isin(selected_ids)]

        if not group_exercises.empty:
            num_to_select = min(count, len(group_exercises))
            chosen = group_exercises.sample(n=num_to_select)
            selected_exercises.extend(chosen.to_dict('records'))
            selected_ids.update(chosen['id'].tolist())
        else:
            print(f"Warning: No new exercises found for target group: {group}")

    # Fill remaining slots randomly if needed
    current_count = len(selected_ids)
    if current_count < num_exercises_target:
        needed = num_exercises_target - current_count
        remaining_available = available_exercises[~available_exercises['id'].isin(selected_ids)]
        if len(remaining_available) >= needed:
            print(f"Filling {needed} remaining slots randomly.")
            filler = remaining_available.sample(n=needed)
            selected_exercises.extend(filler.to_dict('records'))
            selected_ids.update(filler['id'].tolist())
        else:
            print(f"Warning: Could only find {len(remaining_available)} extra exercises.")
            selected_exercises.extend(remaining_available.to_dict('records'))
            selected_ids.update(remaining_available['id'].tolist())

    if not selected_ids:
        return None # Failed to select any exercises

    final_exercise_ids = [ex['id'] for ex in selected_exercises]
    random.shuffle(final_exercise_ids)
    return final_exercise_ids[:num_exercises_target]

def _create_template(name, focus, exercise_ids):
    """Helper function to create the template dictionary."""
    if not exercise_ids:
        return None
    template = {
        "template_name": name,
        "focus": focus,
        "exercises": exercise_ids
    }
    print(f"Generated template: {template}")
    return template

def generate_full_body_template(user_id, user_exercises_details_df, all_exercises_df, num_exercises=7):
    """Generates a simple full-body workout template."""
    print(f"Attempting to generate Full Body template for user {user_id}")
    if all_exercises_df.empty: return None
    user_done_exercise_ids = set(user_exercises_details_df['id']) if not user_exercises_details_df.empty and 'id' in user_exercises_details_df.columns else set()
    if 'id' not in all_exercises_df.columns or 'primaryMuscles' not in all_exercises_df.columns: return None
    available_exercises = all_exercises_df[~all_exercises_df['id'].isin(user_done_exercise_ids) & all_exercises_df['primaryMuscles'].notna()].copy()
    if available_exercises.empty: return None

    target_groups = {
        'Chest': 1,
        'Back': 1,
        'Shoulders': 1,
        'Biceps': 1,
        'Triceps': 1,
        'Legs': 2, # Covers Quads, Hamstrings, Glutes etc.
    }

    exercise_ids = _select_exercises_for_groups(target_groups, available_exercises, user_done_exercise_ids, num_exercises)
    return _create_template("Recommended Full Body", "General Full Body", exercise_ids)

def generate_push_template(user_id, user_exercises_details_df, all_exercises_df, num_exercises=6):
    """Generates a push day workout template (Chest, Shoulders, Triceps)."""
    print(f"Attempting to generate Push template for user {user_id}")
    if all_exercises_df.empty: return None
    user_done_exercise_ids = set(user_exercises_details_df['id']) if not user_exercises_details_df.empty and 'id' in user_exercises_details_df.columns else set()
    if 'id' not in all_exercises_df.columns or 'primaryMuscles' not in all_exercises_df.columns: return None
    available_exercises = all_exercises_df[~all_exercises_df['id'].isin(user_done_exercise_ids) & all_exercises_df['primaryMuscles'].notna()].copy()
    if available_exercises.empty: return None

    target_groups = {
        'Chest': 2,
        'Shoulders': 2,
        'Triceps': 2,
    }

    exercise_ids = _select_exercises_for_groups(target_groups, available_exercises, user_done_exercise_ids, num_exercises)
    return _create_template("Recommended Push Day", "Chest, Shoulders, Triceps", exercise_ids)

def generate_pull_template(user_id, user_exercises_details_df, all_exercises_df, num_exercises=6):
    """Generates a pull day workout template (Back, Biceps)."""
    print(f"Attempting to generate Pull template for user {user_id}")
    if all_exercises_df.empty: return None
    user_done_exercise_ids = set(user_exercises_details_df['id']) if not user_exercises_details_df.empty and 'id' in user_exercises_details_df.columns else set()
    if 'id' not in all_exercises_df.columns or 'primaryMuscles' not in all_exercises_df.columns: return None
    available_exercises = all_exercises_df[~all_exercises_df['id'].isin(user_done_exercise_ids) & all_exercises_df['primaryMuscles'].notna()].copy()
    if available_exercises.empty: return None

    target_groups = {
        'Back': 4, # Includes Lats, Traps, Rhomboids etc.
        'Biceps': 2,
    }

    exercise_ids = _select_exercises_for_groups(target_groups, available_exercises, user_done_exercise_ids, num_exercises)
    return _create_template("Recommended Pull Day", "Back, Biceps", exercise_ids)

def generate_legs_template(user_id, user_exercises_details_df, all_exercises_df, num_exercises=6):
    """Generates a leg day workout template."""
    print(f"Attempting to generate Legs template for user {user_id}")
    if all_exercises_df.empty: return None
    user_done_exercise_ids = set(user_exercises_details_df['id']) if not user_exercises_details_df.empty and 'id' in user_exercises_details_df.columns else set()
    if 'id' not in all_exercises_df.columns or 'primaryMuscles' not in all_exercises_df.columns: return None
    available_exercises = all_exercises_df[~all_exercises_df['id'].isin(user_done_exercise_ids) & all_exercises_df['primaryMuscles'].notna()].copy()
    if available_exercises.empty: return None

    target_groups = {
        'Quadriceps': 2,
        'Hamstrings': 2,
        'Glutes': 1,
        'Calves': 1,
        'Legs': 1 # Add one general leg exercise if others are sparse
    }

    exercise_ids = _select_exercises_for_groups(target_groups, available_exercises, user_done_exercise_ids, num_exercises)
    return _create_template("Recommended Leg Day", "Quadriceps, Hamstrings, Glutes, Calves", exercise_ids)

# --- Collaborative Filtering Functions ---
def fetch_exercise_frequencies_from_other_users(exclude_user_id_str):
    """
    Fetches exercise frequencies from all users, excluding the specified user.
    Returns a DataFrame with 'exercise_id' and 'frequency'.
    """
    try:
        workouts_resp = supabase.table('workouts').select('id, user_id').execute()
        if not workouts_resp.data:
            print("No workouts found at all for collaborative filtering.")
            return pd.DataFrame()
        workouts_df = pd.DataFrame(workouts_resp.data)

        other_users_workouts_df = workouts_df[workouts_df['user_id'] != exclude_user_id_str]
        if other_users_workouts_df.empty:
            print(f"No workouts found for users other than {exclude_user_id_str}")
            return pd.DataFrame()

        other_user_workout_ids = other_users_workouts_df['id'].tolist()
        if not other_user_workout_ids:
             print(f"No workout IDs found for other users.")
             return pd.DataFrame()

        all_workout_exercises_resp = supabase.table('workout_exercises').select('exercise_id, workout_id').execute()
        if not all_workout_exercises_resp.data:
            print("No workout_exercises found at all for collaborative filtering.")
            return pd.DataFrame()
        all_workout_exercises_df = pd.DataFrame(all_workout_exercises_resp.data)

        relevant_workout_exercises_df = all_workout_exercises_df[
            all_workout_exercises_df['workout_id'].isin(other_user_workout_ids)
        ]

        if relevant_workout_exercises_df.empty:
            print(f"No exercises found in workouts of other users.")
            return pd.DataFrame()
        
        if 'exercise_id' not in relevant_workout_exercises_df.columns:
            print("Error: 'exercise_id' column missing from other users' workout exercises.")
            return pd.DataFrame()

        exercise_counts = relevant_workout_exercises_df['exercise_id'].value_counts().reset_index()
        exercise_counts.columns = ['exercise_id', 'frequency']
        return exercise_counts

    except Exception as e:
        print(f"Error fetching exercise frequencies from other users: {e}")
        return pd.DataFrame()

def generate_collaborative_template(user_id, user_exercises_details_df, all_exercises_df, num_exercises=5):
    """Generates a workout template based on exercises popular among other users."""
    print(f"Attempting to generate Collaborative template for user {user_id}")

    other_users_exercise_freq_df = fetch_exercise_frequencies_from_other_users(user_id)

    if other_users_exercise_freq_df.empty or 'exercise_id' not in other_users_exercise_freq_df.columns:
        print(f"No exercise frequency data found from other users for collaborative filtering for user {user_id}.")
        return None

    user_done_exercise_ids = set(user_exercises_details_df['id']) if not user_exercises_details_df.empty and 'id' in user_exercises_details_df.columns else set()

    candidate_exercises_df = other_users_exercise_freq_df[
        ~other_users_exercise_freq_df['exercise_id'].isin(user_done_exercise_ids)
    ]

    if 'id' not in all_exercises_df.columns:
        print("Error: 'id' column missing in all_exercises_df. Cannot validate collaborative candidates.")
        return None
    
    all_valid_exercise_ids = set(all_exercises_df['id'])
    candidate_exercises_df = candidate_exercises_df[
        candidate_exercises_df['exercise_id'].isin(all_valid_exercise_ids)
    ]

    if candidate_exercises_df.empty:
        print(f"No new, valid collaborative exercises found for user {user_id} after filtering.")
        return None

    if 'frequency' not in candidate_exercises_df.columns:
        print("Error: 'frequency' column missing in candidate_exercises_df for collaborative sorting.")
        return None

    selected_exercises_df = candidate_exercises_df.sort_values(by='frequency', ascending=False).head(num_exercises)
    collaborative_exercise_ids = selected_exercises_df['exercise_id'].tolist()

    if not collaborative_exercise_ids:
        print(f"Could not select any collaborative exercises for user {user_id}.")
        return None

    return _create_template(
        "Popular With Others", 
        "Community Favorites", 
        collaborative_exercise_ids
    )

# --- Recommendation Endpoint (Updated for Multiple Templates) ---
@app.route('/recommendations/workout/<user_id>', methods=['GET'])
def get_workout_recommendations(user_id):
    print(f"Received workout recommendation request for user_id: {user_id}")
    if not user_id:
        return jsonify({"error": "User ID is required"}), 400

    # --- Fetch data ---
    all_exercises_df = fetch_all_exercises()
    user_workout_exercises_df, user_exercises_details_df = fetch_user_history(user_id)

    if all_exercises_df.empty:
         print("Error: Could not fetch master exercise list from Supabase.")
         return jsonify({"error": "Could not retrieve exercise data. Cannot generate recommendations."}), 500

    # --- Generate multiple workout template recommendations ---
    possible_templates = []

    # List of generator functions to try
    content_template_generators = [
        generate_full_body_template,
        generate_push_template,
        generate_pull_template,
        generate_legs_template,
    ]

    # Shuffle the generators to provide variety in the order they appear if fewer than target are generated
    random.shuffle(content_template_generators) # Shuffle content-based ones first

    for generator in content_template_generators:
        template = generator(
            user_id,
            user_exercises_details_df,
            all_exercises_df
        )
        if template:
            possible_templates.append(template)

    # --- Generate collaborative filtering recommendations ---
    collaborative_template = generate_collaborative_template(
        user_id,
        user_exercises_details_df,
        all_exercises_df,
        num_exercises=5 # Specify number of collaborative exercises
    )
    if collaborative_template:
        possible_templates.append(collaborative_template)

    # Shuffle all templates together before sampling
    random.shuffle(possible_templates)

    # Select desired number of templates (e.g., 3 to 5)
    num_to_return = min(len(possible_templates), random.randint(3, 5))
    recommended_templates = random.sample(possible_templates, num_to_return) if possible_templates else []

    if not recommended_templates:
        print(f"No workout templates could be generated for user {user_id}.")
        return jsonify({"message": "No specific workout recommendations available at this time.", "recommendations": []}), 200

    # Return the selected templates
    return jsonify({"recommendations": recommended_templates})

@app.route('/recommendations/<user_id>', methods=['GET'])
def get_recommendations_old(user_id):
    return jsonify({"error": "This endpoint is deprecated. Use /recommendations/workout/<user_id>"}), 404

if __name__ == '__main__':
    app.run(debug=True)  # debug=True for development only
