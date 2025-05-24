import os
import pandas as pd  # Add pandas import
from collections import Counter  # Add Counter import
import random  # Add random import
from datetime import datetime, timedelta # Add datetime imports
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

# Simple in-memory cache for exercises
cached_exercises_df = None

@app.route('/')
def home():
    return "HeronFit Recommendation Engine is running!"

# --- Data Fetching Functions ---
def fetch_all_exercises():
    """Fetches all exercises from the Supabase 'exercises' table, using cache."""
    global cached_exercises_df
    if cached_exercises_df is not None:
        print("Using cached exercises data.")
        return cached_exercises_df

    print("Fetching exercises data from Supabase...")
    try:
        response = supabase.table('exercises').select('id, name, primaryMuscles, equipment, category, level').execute()
        if response.data:
            cached_exercises_df = pd.DataFrame(response.data)
            print(f"Fetched and cached {len(cached_exercises_df)} exercises.")
            return cached_exercises_df
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
            return pd.DataFrame(workout_exercises_response.data), pd.DataFrame()

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

# Add a function to fetch the user's goal
def fetch_user_goal(user_id):
    """Fetches the goal for a given user_id from the Supabase 'users' table."""
    try:
        response = supabase.table('users').select('goal').eq('id', user_id).single().execute()
        if response.data and 'goal' in response.data:
            return response.data['goal']
        else:
            print(f"No goal found for user_id: {user_id}")
            return None
    except Exception as e:
        print(f"Error fetching user goal for user_id {user_id}: {e}")
        return None

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

def generate_full_body_template(user_id, user_exercises_details_df, all_exercises_df, user_goal=None, num_exercises=7):
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

    # Adjust target groups based on user goal to aim for a moderate total (around 7-9)
    if user_goal == 'build_muscle':
        print(f"Adjusting Full Body template for goal: {user_goal} (aiming for 8-9 exercises)")
        target_groups['Chest'] = 2
        target_groups['Back'] = 2
        target_groups['Legs'] = 2 # Keep legs at 2 for overall balance in moderate volume
        target_groups['Shoulders'] = 1 # Reduce shoulders slightly in full body for balance
        target_groups['Biceps'] = 1
        target_groups['Triceps'] = 1
        # Total = 2 + 2 + 1 + 1 + 1 + 2 = 9
        num_exercises = 9
    elif user_goal == 'lose_weight':
        print(f"Adjusting Full Body template for goal: {user_goal} (aiming for 7-8 exercises)")
        # Emphasize large muscle groups and compound movements for calorie burn
        target_groups['Legs'] = 2
        target_groups['Back'] = 2
        target_groups['Chest'] = 1
        # Reduce isolation
        target_groups['Biceps'] = 1
        target_groups['Triceps'] = 1
        target_groups['Shoulders'] = 1
         # Total = 2 + 2 + 1 + 1 + 1 + 1 = 8
        num_exercises = 8
    elif user_goal == 'general_fitness':
        print(f"Using default Full Body template for goal: {user_goal} (aiming for 7 exercises)")
        # Default distribution aims for 7 exercises and is generally good for overall fitness
        num_exercises = 7 # Ensure num_exercises matches default sum
        pass # Keep default target_groups
    else:
         print(f"No specific goal or unhandled goal '{user_goal}', using default Full Body distribution (aiming for 7 exercises).")
         num_exercises = 7 # Ensure num_exercises matches default sum
         pass # Keep default target_groups for None or unhandled goals

    exercise_ids = _select_exercises_for_groups(target_groups, available_exercises, user_done_exercise_ids, num_exercises)
    return _create_template("Recommended Full Body", "General Full Body", exercise_ids)

def generate_push_template(user_id, user_exercises_details_df, all_exercises_df, user_goal=None, num_exercises=6):
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

    # Adjust target groups based on user goal to aim for a moderate total (around 6-8)
    if user_goal == 'build_muscle':
        print(f"Adjusting Push template for goal: {user_goal} (aiming for 7-8 exercises)")
        target_groups['Chest'] = 3 # More chest volume
        target_groups['Shoulders'] = 3 # More shoulder volume
        target_groups['Triceps'] = 2 # Keep triceps volume as is
        # Total = 3 + 3 + 2 = 8
        num_exercises = 8
    elif user_goal == 'lose_weight':
        print(f"Adjusting Push template for goal: {user_goal} (aiming for 6-7 exercises)")
        # Focus on compound movements that hit multiple push muscles
        target_groups['Chest'] = 2
        target_groups['Shoulders'] = 2
        target_groups['Triceps'] = 2 # Keep triceps for balanced push
        # Total = 2 + 2 + 2 = 6
        num_exercises = 6
    elif user_goal == 'general_fitness':
        print(f"Using default Push template for goal: {user_goal} (aiming for 6 exercises)")
        # Default distribution aims for 6 exercises and is generally good for overall fitness
        num_exercises = 6
        pass # Keep default target_groups
    else:
         print(f"No specific goal or unhandled goal '{user_goal}', using default Push distribution (aiming for 6 exercises).")
         num_exercises = 6
         pass # Keep default target_groups for None or unhandled goals

    exercise_ids = _select_exercises_for_groups(target_groups, available_exercises, user_done_exercise_ids, num_exercises)
    return _create_template("Recommended Push Day", "Chest, Shoulders, Triceps", exercise_ids)

def generate_pull_template(user_id, user_exercises_details_df, all_exercises_df, user_goal=None, num_exercises=6):
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

    # Adjust target groups based on user goal to aim for a moderate total (around 6-8)
    if user_goal == 'build_muscle':
        print(f"Adjusting Pull template for goal: {user_goal} (aiming for 7-8 exercises)")
        target_groups['Back'] = 5 # More back volume
        target_groups['Biceps'] = 3 # More biceps volume
        # Total = 5 + 3 = 8
        num_exercises = 8
    elif user_goal == 'lose_weight':
        print(f"Adjusting Pull template for goal: {user_goal} (aiming for 6-7 exercises)")
        # Focus on compound back movements
        target_groups['Back'] = 4 # Keep back volume for compound lifts
        target_groups['Biceps'] = 2 # Keep biceps volume for balance
        # Total = 4 + 2 = 6
        num_exercises = 6
    elif user_goal == 'general_fitness':
        print(f"Using default Pull template for goal: {user_goal} (aiming for 6 exercises)")
        # Default distribution aims for 6 exercises and is generally good for overall fitness
        num_exercises = 6
        pass # Keep default target_groups
    else:
         print(f"No specific goal or unhandled goal '{user_goal}', using default Pull distribution (aiming for 6 exercises).")
         num_exercises = 6
         pass # Keep default target_groups for None or unhandled goals

    exercise_ids = _select_exercises_for_groups(target_groups, available_exercises, user_done_exercise_ids, num_exercises)
    return _create_template("Recommended Pull Day", "Back, Biceps", exercise_ids)

def generate_legs_template(user_id, user_exercises_details_df, all_exercises_df, user_goal=None, num_exercises=6):
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

    # Adjust target groups based on user goal to aim for a moderate total (around 6-8)
    if user_goal == 'build_muscle':
        print(f"Adjusting Legs template for goal: {user_goal} (aiming for 7-8 exercises)")
        target_groups['Quadriceps'] = 3
        target_groups['Hamstrings'] = 3
        target_groups['Glutes'] = 2
        target_groups['Calves'] = 1 # Keep calves at 1 for overall leg focus
        # Total = 3 + 3 + 2 + 1 = 9 (Adjusting to 8)
        target_groups['Glutes'] = 1 # Reduce glutes to 1 to get closer to 8
        # Total = 3 + 3 + 1 + 1 = 8
        num_exercises = 8
    elif user_goal == 'lose_weight':
        print(f"Adjusting Legs template for goal: {user_goal} (aiming for 6-7 exercises)")
        # Focus on compound leg movements for calorie burn
        target_groups['Quadriceps'] = 2
        target_groups['Hamstrings'] = 2
        target_groups['Glutes'] = 1
        target_groups['Calves'] = 1
        # Total = 2 + 2 + 1 + 1 = 6
        num_exercises = 6
    elif user_goal == 'general_fitness':
        print(f"Using default Legs template for goal: {user_goal} (aiming for 6 exercises)")
        # Default distribution aims for 6 exercises and is generally good for overall fitness
        num_exercises = 6
        pass # Keep default target_groups
    else:
         print(f"No specific goal or unhandled goal '{user_goal}', using default Legs distribution (aiming for 6 exercises).")
         num_exercises = 6
         pass # Keep default target_groups for None or unhandled goals

    # Remove the general 'Legs' category if specific groups are targeted
    if user_goal in ['build_muscle', 'lose_weight', 'general_fitness']:
        if 'Legs' in target_groups:
            del target_groups['Legs']
            print("Removed general 'Legs' target as specific groups are prioritized.")

    exercise_ids = _select_exercises_for_groups(target_groups, available_exercises, user_done_exercise_ids, num_exercises)
    return _create_template("Recommended Leg Day", "Quadriceps, Hamstrings, Glutes, Calves", exercise_ids)

# --- Collaborative Filtering Functions ---
def fetch_exercise_frequencies_from_other_users(exclude_user_id_str, user_goal):
    """
    Fetches exercise frequencies from all users with the same goal,
    excluding the specified user.
    Returns a DataFrame with 'exercise_id' and 'frequency'.
    """
    try:
        # First, get the IDs of users with the same goal, excluding the current user
        if user_goal:
            users_resp = supabase.table('users').select('id') \
                .eq('goal', user_goal) \
                .neq('id', exclude_user_id_str) \
                .execute()
            if not users_resp.data:
                print(f"No other users found with goal: {user_goal}")
                return pd.DataFrame()
            other_user_ids_with_goal = [u['id'] for u in users_resp.data]
            if not other_user_ids_with_goal:
                print(f"No other user IDs found with goal: {user_goal}")
                return pd.DataFrame()
        else:
            # If no goal is provided, fetch all other user IDs
            print("User goal not specified, fetching exercise frequency from ALL other users.")
            users_resp = supabase.table('users').select('id') \
                 .neq('id', exclude_user_id_str) \
                 .execute()
            if not users_resp.data:
                print("No other users found.")
                return pd.DataFrame()
            other_user_ids_with_goal = [u['id'] for u in users_resp.data]
            if not other_user_ids_with_goal:
                print("No other user IDs found.")
                return pd.DataFrame()


        # Now fetch workouts only for those users
        workouts_resp = supabase.table('workouts').select('id, user_id') \
            .in_('user_id', other_user_ids_with_goal) \
            .execute()

        if not workouts_resp.data:
            print(f"No workouts found for other users with goal {user_goal}.")
            return pd.DataFrame()
        workouts_df = pd.DataFrame(workouts_resp.data)

        # The rest of the logic remains the same
        other_user_workout_ids = workouts_df['id'].tolist()
        if not other_user_workout_ids:
            print(f"No workout IDs found for other users with goal {user_goal}.")
            return pd.DataFrame()

        # Now fetch workout exercises only for those workouts
        workout_exercises_resp = supabase.table('workout_exercises').select('exercise_id, workout_id')\
             .in_('workout_id', other_user_workout_ids)\
             .execute()

        if not workout_exercises_resp.data:
            print(f"No exercises found in workouts of other users with goal {user_goal}.")
            return pd.DataFrame()
        relevant_workout_exercises_df = pd.DataFrame(workout_exercises_resp.data)

        if 'exercise_id' not in relevant_workout_exercises_df.columns:
            print("Error: 'exercise_id' column missing from other users' workout exercises.")
            return pd.DataFrame()

        exercise_counts = relevant_workout_exercises_df['exercise_id'].value_counts().reset_index()
        exercise_counts.columns = ['exercise_id', 'frequency']
        return exercise_counts

    except Exception as e:
        print(f"Error fetching exercise frequencies from other users (with goal filter): {e}")
        return pd.DataFrame()

def generate_collaborative_template(user_id, user_exercises_details_df, all_exercises_df, user_goal=None, num_exercises=5):
    """Generates a workout template based on exercises popular among other users."""
    print(f"Attempting to generate Collaborative template for user {user_id}")

    other_users_exercise_freq_df = fetch_exercise_frequencies_from_other_users(user_id, user_goal) # Pass the user_goal

    user_done_exercise_ids = set(user_exercises_details_df['id']) if not user_exercises_details_df.empty and 'id' in user_exercises_details_df.columns else set()

    candidate_exercises_df = pd.DataFrame()
    if not other_users_exercise_freq_df.empty and 'exercise_id' in other_users_exercise_freq_df.columns:
        candidate_exercises_df = other_users_exercise_freq_df[
            ~other_users_exercise_freq_df['exercise_id'].isin(user_done_exercise_ids)
        ]

    collaborative_exercise_ids = []
    template_name = "Popular With Others"
    template_focus = "Community Favorites"

    if not candidate_exercises_df.empty and 'frequency' in candidate_exercises_df.columns:
        selected_exercises_df = candidate_exercises_df.sort_values(by='frequency', ascending=False).head(num_exercises)
        collaborative_exercise_ids = selected_exercises_df['exercise_id'].tolist()
        template_name = "Popular With Others (Same Goal)" if user_goal else "Popular With Others"
        template_focus = f"Community Favorites ({user_goal})" if user_goal else "Community Favorites"

        if len(collaborative_exercise_ids) < num_exercises:
            needed_more = num_exercises - len(collaborative_exercise_ids)
            print(f"Collaborative selection yielded {len(collaborative_exercise_ids)} exercises, needing {needed_more} more for target of {num_exercises}.")
            # Fallback/Filler logic - will be handled below to avoid repetition

    if not collaborative_exercise_ids:
        print(f"No collaborative exercises found for user {user_id} (with goal {user_goal}). Falling back to random selection.")
        # Fallback: Select random exercises if no collaborative candidates found
        ids_to_exclude_from_filler = user_done_exercise_ids
        if 'id' in all_exercises_df.columns:
            available_for_filler_df = all_exercises_df[~all_exercises_df['id'].isin(ids_to_exclude_from_filler)]
            if not available_for_filler_df.empty:
                num_to_sample = min(num_exercises, len(available_for_filler_df))
                if num_to_sample > 0:
                    filler_exercises_df = available_for_filler_df.sample(n=num_to_sample)
                    collaborative_exercise_ids = filler_exercises_df['id'].tolist()
                    print(f"Added {len(collaborative_exercise_ids)} random filler exercises as fallback.")
                    template_name = "Community Picks (General)" # Indicate these are general picks
                    template_focus = "Diverse Exercises"
                else:
                    print("No exercises available for random filling (num_to_sample was 0).")
            else:
                print("No exercises available for random filling after exclusions.")
        else:
            print("Could not add fillers: 'id' column missing in all_exercises_df.")


    if not collaborative_exercise_ids:
        print(f"Could not select any collaborative exercises for user {user_id}, even after fallback.")
        return None

    # Ensure we return the target number of exercises if possible
    final_ids_for_template = collaborative_exercise_ids[:num_exercises]

    if not final_ids_for_template:
         print(f"Final list of collaborative exercise IDs is empty for user {user_id}.")
         return None

    return _create_template(
        template_name,
        template_focus,
        final_ids_for_template
    )

# --- Time-Filtered Collaborative Filtering Functions ---
def fetch_exercise_frequencies_with_time_filter(exclude_user_id_str, start_date_iso, end_date_iso, user_goal):
    """
    Fetches exercise frequencies from other users with the same goal
    within a specific time window.
    Returns a DataFrame with 'exercise_id' and 'frequency'.
    """
    try:
        # First, get the IDs of users with the same goal, excluding the current user
        if user_goal:
            users_resp = supabase.table('users').select('id') \
                .eq('goal', user_goal) \
                .neq('id', exclude_user_id_str) \
                .execute()
            if not users_resp.data:
                print(f"No other users found with goal: {user_goal} in time-filtered search.")
                return pd.DataFrame()
            other_user_ids_with_goal = [u['id'] for u in users_resp.data]
            if not other_user_ids_with_goal:
                print(f"No other user IDs found with goal: {user_goal} in time-filtered search.")
                return pd.DataFrame()
        else:
            # If no goal is provided, fetch all other user IDs
            print("User goal not specified, fetching time-filtered exercise frequency from ALL other users.")
            users_resp = supabase.table('users').select('id') \
                 .neq('id', exclude_user_id_str) \
                 .execute()
            if not users_resp.data:
                print("No other users found in time-filtered search.")
                return pd.DataFrame()
            other_user_ids_with_goal = [u['id'] for u in users_resp.data]
            if not other_user_ids_with_goal:
                print("No other user IDs found in time-filtered search.")
                return pd.DataFrame()

        # Fetch workouts for those users within the time window
        workouts_resp = supabase.table('workouts').select('id, user_id, timestamp') \
            .in_('user_id', other_user_ids_with_goal) \
            .gte('timestamp', start_date_iso) \
            .lte('timestamp', end_date_iso) \
            .execute()

        if not workouts_resp.data:
            print(f"No workouts found for other users with goal {user_goal} between {start_date_iso} and {end_date_iso}.")
            return pd.DataFrame()

        other_user_workout_ids = [w['id'] for w in workouts_resp.data]
        if not other_user_workout_ids:
            print(f"No workout IDs found for other users with goal {user_goal} in the time window.")
            return pd.DataFrame()

        # Fetch workout exercises for those workouts
        workout_exercises_resp = supabase.table('workout_exercises').select('exercise_id, workout_id')\
            .in_('workout_id', other_user_workout_ids)\
            .execute()

        if not workout_exercises_resp.data:
            print(f"No exercises found in workouts of other users with goal {user_goal} within the time window.")
            return pd.DataFrame()
        relevant_workout_exercises_df = pd.DataFrame(workout_exercises_resp.data)


        if 'exercise_id' not in relevant_workout_exercises_df.columns:
            print("Error: 'exercise_id' column missing from other users' workout exercises (time-filtered).")
            return pd.DataFrame()

        exercise_counts = relevant_workout_exercises_df['exercise_id'].value_counts().reset_index()
        exercise_counts.columns = ['exercise_id', 'frequency']
        return exercise_counts

    except Exception as e:
        print(f"Error fetching time-filtered exercise frequencies (with goal filter): {e}")
        return pd.DataFrame()

def generate_popular_recent_template(user_id, user_exercises_details_df, all_exercises_df, time_delta, template_title_base, template_focus_base, user_goal=None, num_exercises=5):
    """Generates a template based on exercises popular among other users in a recent time window."""
    print(f"Attempting to generate '{template_title_base}' template for user {user_id} (timedelta: {time_delta.days} days, goal: {user_goal})")

    end_date = datetime.utcnow()
    start_date = end_date - time_delta
    start_date_iso = start_date.isoformat()
    end_date_iso = end_date.isoformat()

    recent_exercise_freq_df = fetch_exercise_frequencies_with_time_filter(user_id, start_date_iso, end_date_iso, user_goal) # Pass the user_goal

    user_done_exercise_ids = set(user_exercises_details_df['id']) if not user_exercises_details_df.empty and 'id' in user_exercises_details_df.columns else set()

    candidate_exercises_df = pd.DataFrame()
    if not recent_exercise_freq_df.empty and 'exercise_id' in recent_exercise_freq_df.columns:
         candidate_exercises_df = recent_exercise_freq_df[
            ~recent_exercise_freq_df['exercise_id'].isin(user_done_exercise_ids)
        ]

    final_exercise_ids = []
    template_name = template_title_base + (f" ({user_goal})" if user_goal else "")
    template_focus = template_focus_base + (f" ({user_goal})" if user_goal else "")


    if not candidate_exercises_df.empty and 'frequency' in candidate_exercises_df.columns:
        selected_exercises_df = candidate_exercises_df.sort_values(by='frequency', ascending=False).head(num_exercises)
        final_exercise_ids = selected_exercises_df['exercise_id'].tolist()

        if len(final_exercise_ids) < num_exercises:
            needed_more = num_exercises - len(final_exercise_ids)
            print(f"Recent popular selection for '{template_title_base}' yielded {len(final_exercise_ids)}, needing {needed_more} more.")
            # Fallback/Filler logic - will be handled below to avoid repetition

    if not final_exercise_ids:
        print(f"No recent collaborative exercises found for user {user_id} (with goal {user_goal}). Falling back to random selection.")
        # Fallback: Select random exercises if no collaborative candidates found
        ids_to_exclude_from_filler = user_done_exercise_ids
        if 'id' in all_exercises_df.columns:
            available_for_filler_df = all_exercises_df[~all_exercises_df['id'].isin(ids_to_exclude_from_filler)]
            if not available_for_filler_df.empty:
                num_to_sample = min(num_exercises, len(available_for_filler_df))
                if num_to_sample > 0:
                    filler_exercises_df = available_for_filler_df.sample(n=num_to_sample)
                    final_exercise_ids = filler_exercises_df['id'].tolist()
                    print(f"Added {len(final_exercise_ids)} random filler exercises as fallback for '{template_title_base}'.")
                    template_name = f"{template_title_base} (General Picks)" # Indicate these are general picks
                    template_focus = "Diverse Exercises"
                else:
                    print("No exercises available for random filling (num_to_sample was 0).")
            else:
                print(f"No exercises available for random filling for '{template_title_base}' after exclusions.")
        else:
            print(f"Could not add fillers to '{template_title_base}': 'id' column missing in all_exercises_df.")


    if not final_exercise_ids:
        print(f"Could not select any exercises for '{template_title_base}' for user {user_id}, even after fallback.")
        return None

    # Ensure we return the target number of exercises if possible
    final_ids_for_template = final_exercise_ids[:num_exercises]

    if not final_ids_for_template:
         print(f"Final list of collaborative exercise IDs for '{template_title_base}' is empty for user {user_id}.")
         return None

    return _create_template(template_name, template_focus, final_ids_for_template)

# --- Recommendation Endpoint (Updated for Multiple Templates) ---
@app.route('/recommendations/workout/<user_id>', methods=['GET'])
def get_workout_recommendations(user_id):
    print(f"Received workout recommendation request for user_id: {user_id}")
    if not user_id:
        return jsonify({"error": "User ID is required"}), 400

    # --- Fetch data ---
    all_exercises_df = fetch_all_exercises() # This function now uses the cache
    user_workout_exercises_df, user_exercises_details_df = fetch_user_history(user_id)
    user_goal = fetch_user_goal(user_id) # Fetch the user's goal

    if all_exercises_df.empty:
         print("Error: Could not fetch master exercise list from Supabase.")
         return jsonify({"error": "Could not retrieve exercise data. Cannot generate recommendations."}), 500

    # --- Generate multiple workout template recommendations ---
    content_templates = []
    collaborative_templates_generated = []

    # List of content-based generator functions to try
    content_template_generators = [
        generate_full_body_template,
        generate_push_template,
        generate_pull_template,
        generate_legs_template,
    ]
    random.shuffle(content_template_generators) # Shuffle to vary which ones are tried first

    for generator in content_template_generators:
        template = generator(
            user_id,
            user_exercises_details_df,
            all_exercises_df,
            user_goal=user_goal # Pass the user's goal
        )
        if template:
            content_templates.append(template)

    # --- Generate general collaborative filtering recommendations ---
    general_collaborative_template = generate_collaborative_template(
        user_id,
        user_exercises_details_df,
        all_exercises_df,
        num_exercises=5,
        user_goal=user_goal # Pass the user's goal
    )
    if general_collaborative_template:
        collaborative_templates_generated.append(general_collaborative_template)

    # --- Generate time-filtered collaborative recommendations ---
    weekly_popular_template = generate_popular_recent_template(
        user_id,
        user_exercises_details_df,
        all_exercises_df,
        time_delta=timedelta(days=7),
        template_title_base="Popular This Week",
        template_focus_base="Trending Weekly",
        num_exercises=5,
        user_goal=user_goal # Pass the user's goal
    )
    if weekly_popular_template:
        collaborative_templates_generated.append(weekly_popular_template)

    monthly_popular_template = generate_popular_recent_template(
        user_id,
        user_exercises_details_df,
        all_exercises_df,
        time_delta=timedelta(days=30),
        template_title_base="Popular This Month",
        template_focus_base="Trending Monthly",
        num_exercises=5,
        user_goal=user_goal # Pass the user's goal
    )
    if monthly_popular_template:
        collaborative_templates_generated.append(monthly_popular_template)

    # Shuffle each list internally for varied presentation within categories
    random.shuffle(content_templates)
    random.shuffle(collaborative_templates_generated)

    if not content_templates and not collaborative_templates_generated:
        print(f"No workout templates could be generated for user {user_id}.")
        return jsonify({
            "message": "No specific workout recommendations available at this time.",
            "for_you_recommendations": [],
            "community_recommendations": []
        }), 200

    # Return all generated templates, categorized
    return jsonify({
        "for_you_recommendations": content_templates,
        "community_recommendations": collaborative_templates_generated
    })

@app.route('/recommendations/<user_id>', methods=['GET'])
def get_recommendations_old(user_id):
    return jsonify({"error": "This endpoint is deprecated. Use /recommendations/workout/<user_id>"}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)  # Allow external connections for development
