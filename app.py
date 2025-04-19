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
def generate_full_body_template(user_id, user_exercises_details_df, all_exercises_df, num_exercises=7):
    """Generates a simple full-body workout template."""
    print(f"Generating full body template for user {user_id}")

    if all_exercises_df.empty:
        print("Cannot generate template: all_exercises_df is empty.")
        return None

    # Define target muscle groups for a balanced full-body workout
    target_groups = {
        'Chest': 1,
        'Back': 1,
        'Shoulders': 1,
        'Biceps': 1,
        'Triceps': 1,
        'Legs': 2,
    }
    target_exercise_count = sum(target_groups.values())

    # Get IDs of exercises user has already done
    user_done_exercise_ids = set()
    if not user_exercises_details_df.empty and 'id' in user_exercises_details_df.columns:
        user_done_exercise_ids = set(user_exercises_details_df['id'])
        print(f"User {user_id} has done {len(user_done_exercise_ids)} unique exercises.")

    # Filter available exercises: exclude done ones and ensure primaryMuscles exists
    if 'id' not in all_exercises_df.columns or 'primaryMuscles' not in all_exercises_df.columns:
        print("Error: 'id' or 'primaryMuscles' missing from all_exercises_df.")
        return None

    available_exercises = all_exercises_df[
        ~all_exercises_df['id'].isin(user_done_exercise_ids) &
        all_exercises_df['primaryMuscles'].notna()
    ].copy()

    if available_exercises.empty:
        print(f"No available new exercises found for user {user_id}. Cannot generate template.")
        return None

    # Helper to check if an exercise targets a group
    def targets_group(exercise_muscles, group_name):
        if not exercise_muscles: return False
        if isinstance(exercise_muscles, list):
            return any(group_name.lower() in m.lower() for m in exercise_muscles)
        elif isinstance(exercise_muscles, str):
            return group_name.lower() in exercise_muscles.lower()
        return False

    selected_exercises = []
    selected_ids = set()

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

    # Fill remaining slots randomly
    current_count = len(selected_ids)
    if current_count < num_exercises:
        needed = num_exercises - current_count
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
        print("Failed to select any exercises for the template.")
        return None

    final_exercise_ids = [ex['id'] for ex in selected_exercises]
    random.shuffle(final_exercise_ids)

    template = {
        "template_name": "Recommended Full Body Workout",
        "focus": "General Full Body",
        "exercises": final_exercise_ids[:num_exercises]
    }

    print(f"Generated template: {template}")
    return template

# --- Recommendation Endpoint (Updated for Templates) ---
@app.route('/recommendations/workout/<user_id>', methods=['GET'])
def get_workout_recommendations(user_id):
    print(f"Received workout recommendation request for user_id: {user_id}")
    if not user_id:
        return jsonify({"error": "User ID is required"}), 400

    all_exercises_df = fetch_all_exercises()
    user_workout_exercises_df, user_exercises_details_df = fetch_user_history(user_id)

    if all_exercises_df.empty:
        print("Error: Could not fetch master exercise list from Supabase.")
        return jsonify({"error": "Could not retrieve exercise data. Cannot generate recommendations."}), 500

    recommended_template = generate_full_body_template(
        user_id,
        user_exercises_details_df,
        all_exercises_df,
        num_exercises=7
    )

    if not recommended_template:
        print(f"No workout template could be generated for user {user_id}.")
        return jsonify({"message": "No specific workout recommendations available at this time.", "recommendations": []}), 200

    return jsonify({"recommendations": [recommended_template]})

# Update the old endpoint route to avoid conflict or remove it
@app.route('/recommendations/<user_id>', methods=['GET'])
def get_recommendations_old(user_id):
    return jsonify({"error": "This endpoint is deprecated. Use /recommendations/workout/<user_id>"}), 404

if __name__ == '__main__':
    app.run(debug=True)  # debug=True for development only
