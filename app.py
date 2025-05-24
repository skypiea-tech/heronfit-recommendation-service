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

    # Adjust target groups based on user goal
    if user_goal == 'build_muscle':
        print(f"Adjusting Full Body template for goal: {user_goal}")
        target_groups['Chest'] = 2
        target_groups['Back'] = 2
        target_groups['Legs'] = 3 # More leg volume for muscle building
        target_groups['Shoulders'] = 2
        # Keep biceps and triceps at 1 for a full body split
        num_exercises = max(num_exercises, sum(target_groups.values())) # Ensure enough exercises to meet targets
    elif user_goal == 'lose_weight':
        print(f"Adjusting Full Body template for goal: {user_goal}")
        # Emphasize large muscle groups and compound movements for calorie burn
        target_groups['Legs'] = 3
        target_groups['Back'] = 2
        target_groups['Chest'] = 2
        # Reduce isolation slightly, focus on compound for efficiency
        target_groups['Biceps'] = 0 # Focus on compound movements that hit biceps/triceps
        target_groups['Triceps'] = 0
        # Ensure shoulders are still included as they are a large group
        target_groups['Shoulders'] = 1
        num_exercises = max(num_exercises, sum(target_groups.values())) # Ensure enough exercises to meet targets
    elif user_goal == 'general_fitness':
        print(f"Using default Full Body template for goal: {user_goal}")
        # Default distribution is generally good for overall fitness
        pass # Keep default target_groups
    else:
         print(f"No specific goal or unhandled goal '{user_goal}', using default Full Body distribution.")
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

    # Adjust target groups based on user goal
    if user_goal == 'build_muscle':
        print(f"Adjusting Push template for goal: {user_goal}")
        target_groups['Chest'] = 3 # More chest volume
        target_groups['Shoulders'] = 3 # More shoulder volume
        target_groups['Triceps'] = 2 # Keep triceps volume as is
        num_exercises = max(num_exercises, sum(target_groups.values()))
    elif user_goal == 'lose_weight':
        print(f"Adjusting Push template for goal: {user_goal}")
        # Focus on compound movements that hit multiple push muscles
        target_groups['Chest'] = 2
        target_groups['Shoulders'] = 2
        target_groups['Triceps'] = 1 # Slightly less triceps isolation
        num_exercises = max(num_exercises, sum(target_groups.values()))
    elif user_goal == 'general_fitness':
        print(f"Using default Push template for goal: {user_goal}")
        pass # Keep default target_groups
    else:
         print(f"No specific goal or unhandled goal '{user_goal}', using default Push distribution.")
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

    # Adjust target groups based on user goal
    if user_goal == 'build_muscle':
        print(f"Adjusting Pull template for goal: {user_goal}")
        target_groups['Back'] = 5 # More back volume
        target_groups['Biceps'] = 3 # More biceps volume
        num_exercises = max(num_exercises, sum(target_groups.values()))
    elif user_goal == 'lose_weight':
        print(f"Adjusting Pull template for goal: {user_goal}")
        # Focus on compound back movements
        target_groups['Back'] = 3 # Slightly less back isolation
        target_groups['Biceps'] = 1 # Slightly less biceps isolation
        num_exercises = max(num_exercises, sum(target_groups.values()))
    elif user_goal == 'general_fitness':
        print(f"Using default Pull template for goal: {user_goal}")
        pass # Keep default target_groups
    else:
         print(f"No specific goal or unhandled goal '{user_goal}', using default Pull distribution.")
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

    # Adjust target groups based on user goal
    if user_goal == 'build_muscle':
        print(f"Adjusting Legs template for goal: {user_goal}")
        target_groups['Quadriceps'] = 3
        target_groups['Hamstrings'] = 3
        target_groups['Glutes'] = 2
        target_groups['Calves'] = 2
        num_exercises = max(num_exercises, sum(target_groups.values()))
    elif user_goal == 'lose_weight':
        print(f"Adjusting Legs template for goal: {user_goal}")
        # Focus on compound leg movements for calorie burn
        target_groups['Quadriceps'] = 3
        target_groups['Hamstrings'] = 3
        target_groups['Glutes'] = 2
        target_groups['Calves'] = 1 # Slightly less focus on calves
        num_exercises = max(num_exercises, sum(target_groups.values()))
    elif user_goal == 'general_fitness':
        print(f"Using default Legs template for goal: {user_goal}")
        pass # Keep default target_groups
    else:
         print(f"No specific goal or unhandled goal '{user_goal}', using default Legs distribution.")
         pass # Keep default target_groups for None or unhandled goals

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

        all_workout_exercises_resp = supabase.table('workout_exercises').select('exercise_id, workout_id').execute()
        if not all_workout_exercises_resp.data:
            print("No workout_exercises found at all for collaborative filtering.")
            return pd.DataFrame()
        all_workout_exercises_df = pd.DataFrame(all_workout_exercises_resp.data)

        relevant_workout_exercises_df = all_workout_exercises_df[
            all_workout_exercises_df['workout_id'].isin(other_user_workout_ids)
        ]

        if relevant_workout_exercises_df.empty:
            print(f"No exercises found in workouts of other users with goal {user_goal}.")
            return pd.DataFrame()

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

    if other_users_exercise_freq_df.empty or 'exercise_id' not in other_users_exercise_freq_df.columns:
        print(f"No exercise frequency data found from other users (with goal {user_goal}) for collaborative filtering for user {user_id}.")
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
        print(f"No new, valid collaborative exercises found for user {user_id} (with goal {user_goal}) after filtering.")
        return None

    if 'frequency' not in candidate_exercises_df.columns:
        print("Error: 'frequency' column missing in candidate_exercises_df for collaborative sorting.")
        return None

    selected_exercises_df = candidate_exercises_df.sort_values(by='frequency', ascending=False).head(num_exercises)
    collaborative_exercise_ids = selected_exercises_df['exercise_id'].tolist()

    template_name = "Popular With Others (Same Goal)" if user_goal else "Popular With Others"
    template_focus = f"Community Favorites ({user_goal})" if user_goal else "Community Favorites"

    if len(collaborative_exercise_ids) < num_exercises:
        needed_more = num_exercises - len(collaborative_exercise_ids)
        print(f"Collaborative selection yielded {len(collaborative_exercise_ids)} exercises, needing {needed_more} more for target of {num_exercises}.")

        # Prepare IDs already selected or done by user to exclude them from random fillers
        ids_to_exclude_from_filler = set(collaborative_exercise_ids).union(user_done_exercise_ids)

        if 'id' in all_exercises_df.columns:
            available_for_filler_df = all_exercises_df[
                ~all_exercises_df['id'].isin(ids_to_exclude_from_filler)
            ]

            if not available_for_filler_df.empty:
                num_to_sample = min(needed_more, len(available_for_filler_df))
                if num_to_sample > 0:
                    filler_exercises_df = available_for_filler_df.sample(n=num_to_sample)
                    filler_exercise_ids = filler_exercises_df['id'].tolist()
                    collaborative_exercise_ids.extend(filler_exercise_ids)
                    print(f"Added {len(filler_exercise_ids)} random filler exercises.")
                    template_name = f"Popular With Others ({user_goal} & New Picks)" if user_goal else "Community & New Picks"
                    template_focus = f"Popular ({user_goal}) & Randomly Added" if user_goal else "Popular & Randomly Added"
                else:
                    print("No filler exercises could be sampled (num_to_sample was 0).")
            else:
                print("No exercises available for random filling after exclusions.")
        else:
            print("Could not add fillers: 'id' column missing in all_exercises_df.")


    if not collaborative_exercise_ids:
        print(f"Could not select any collaborative exercises for user {user_id}, even after trying fillers.")
        return None

    return _create_template(
        template_name,
        template_focus,
        collaborative_exercise_ids
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

        # Fetch all workout_exercises
        all_workout_exercises_resp = supabase.table('workout_exercises').select('exercise_id, workout_id').execute()
        if not all_workout_exercises_resp.data:
            print("No workout_exercises found at all for time-filtered collaborative filtering.")
            return pd.DataFrame()
        all_workout_exercises_df = pd.DataFrame(all_workout_exercises_resp.data)

        relevant_workout_exercises_df = all_workout_exercises_df[
            all_workout_exercises_df['workout_id'].isin(other_user_workout_ids)
        ]

        if relevant_workout_exercises_df.empty:
            print(f"No exercises found in workouts of other users with goal {user_goal} within the time window.")
            return pd.DataFrame()

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

    if recent_exercise_freq_df.empty or 'exercise_id' not in recent_exercise_freq_df.columns:
        print(f"No recent exercise frequency data found for '{template_title_base}' for user {user_id} (with goal {user_goal}).")
        return None

    user_done_exercise_ids = set(user_exercises_details_df['id']) if not user_exercises_details_df.empty and 'id' in user_exercises_details_df.columns else set()

    candidate_exercises_df = recent_exercise_freq_df[
        ~recent_exercise_freq_df['exercise_id'].isin(user_done_exercise_ids)
    ]

    if 'id' not in all_exercises_df.columns:
        print(f"Error: 'id' column missing in all_exercises_df. Cannot validate for '{template_title_base}'.")
        return None

    all_valid_exercise_ids = set(all_exercises_df['id'])
    candidate_exercises_df = candidate_exercises_df[
        candidate_exercises_df['exercise_id'].isin(all_valid_exercise_ids)
    ]

    if candidate_exercises_df.empty:
        print(f"No new, valid recent exercises for '{template_title_base}' for user {user_id} (with goal {user_goal}) after filtering.")
        return None

    if 'frequency' not in candidate_exercises_df.columns:
        print(f"Error: 'frequency' column missing for '{template_title_base}' sorting.")
        return None

    selected_exercises_df = candidate_exercises_df.sort_values(by='frequency', ascending=False).head(num_exercises)
    final_exercise_ids = selected_exercises_df['exercise_id'].tolist()

    template_name = template_title_base + (f" ({user_goal})" if user_goal else "")
    template_focus = template_focus_base + (f" ({user_goal})" if user_goal else "")

    if len(final_exercise_ids) < num_exercises:
        needed_more = num_exercises - len(final_exercise_ids)
        print(f"Recent popular selection for '{template_title_base}' yielded {len(final_exercise_ids)}, needing {needed_more} more.")

        ids_to_exclude_from_filler = set(final_exercise_ids).union(user_done_exercise_ids)
        if 'id' in all_exercises_df.columns:
            available_for_filler_df = all_exercises_df[~all_exercises_df['id'].isin(ids_to_exclude_from_filler)]
            if not available_for_filler_df.empty:
                num_to_sample = min(needed_more, len(available_for_filler_df))
                if num_to_sample > 0:
                    filler_exercises_df = available_for_filler_df.sample(n=num_to_sample)
                    filler_ids = filler_exercises_df['id'].tolist()
                    final_exercise_ids.extend(filler_ids)
                    print(f"Added {len(filler_ids)} random filler exercises to '{template_title_base}'.")
                    template_name = f"{template_title_base} & New Ideas" + (f" ({user_goal})" if user_goal else "")
                    template_focus = f"{template_focus_base} & Randomly Added" + (f" ({user_goal})" if user_goal else "")

                else:
                    print("No filler exercises could be sampled (num_to_sample was 0).")
            else:
                print(f"No exercises available for random filling for '{template_title_base}'.")
        else:
            print(f"Could not add fillers to '{template_title_base}': 'id' column missing in all_exercises_df.")

    if not final_exercise_ids:
        print(f"Could not select any exercises for '{template_title_base}' for user {user_id}, even after fillers.")
        return None

    return _create_template(template_name, template_focus, final_exercise_ids)

# --- Recommendation Endpoint (Updated for Multiple Templates) ---
@app.route('/recommendations/workout/<user_id>', methods=['GET'])
def get_workout_recommendations(user_id):
    print(f"Received workout recommendation request for user_id: {user_id}")
    if not user_id:
        return jsonify({"error": "User ID is required"}), 400

    # --- Fetch data ---
    all_exercises_df = fetch_all_exercises()
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
