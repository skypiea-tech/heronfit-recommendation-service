import os
import pandas as pd  # Add pandas import
from collections import Counter  # Add Counter import
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
        response = supabase.table('exercises').select('id, name, muscle_group, equipment_required, type, difficulty').execute()
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

        exercise_ids = list(set([we['exercise_id'] for we in workout_exercises_response.data]))
        if not exercise_ids:
            print(f"No valid exercise IDs found in history for user_id: {user_id}")
            return pd.DataFrame(workout_exercises_response.data), pd.DataFrame()

        exercises_details_response = supabase.table('exercises').select('id, name, muscle_group').in_('id', exercise_ids).execute()
        if not exercises_details_response.data:
            print(f"Could not fetch details for exercises: {exercise_ids}")
            return pd.DataFrame(workout_exercises_response.data), pd.DataFrame()

        return pd.DataFrame(workout_exercises_response.data), pd.DataFrame(exercises_details_response.data)

    except Exception as e:
        print(f"Error fetching user history for user_id {user_id}: {e}")
        return pd.DataFrame(), pd.DataFrame()

# --- Basic Content-Based Recommendation Logic ---
def generate_simple_content_recommendations(user_id, user_workout_exercises_df, user_exercises_details_df, all_exercises_df):
    """Generates simple content-based recommendations based on most frequent muscle group."""
    if user_exercises_details_df.empty or all_exercises_df.empty:
        print(f"No history details or all_exercises data for user {user_id}. Recommending top 5 overall exercises.")
        if not all_exercises_df.empty:
            return all_exercises_df.head(5)['id'].tolist()
        else:
            return []

    if 'muscle_group' not in user_exercises_details_df.columns:
        print(f"Warning: 'muscle_group' column not found in user exercise details for user {user_id}.")
        if not all_exercises_df.empty:
            return all_exercises_df.head(5)['id'].tolist()
        else:
            return []

    valid_muscle_groups = user_exercises_details_df['muscle_group'].dropna()
    if valid_muscle_groups.empty:
        print(f"No valid muscle groups found in user {user_id}'s history.")
        if not all_exercises_df.empty:
            return all_exercises_df.head(5)['id'].tolist()
        else:
            return []

    muscle_counts = Counter(valid_muscle_groups)
    most_common_muscle_group = muscle_counts.most_common(1)[0][0]
    print(f"User {user_id}'s most frequent muscle group: {most_common_muscle_group}")

    if 'muscle_group' not in all_exercises_df.columns:
        print("Error: 'muscle_group' column not found in all_exercises_df.")
        return []

    recommended_exercises = all_exercises_df[
        all_exercises_df['muscle_group'] == most_common_muscle_group
    ].copy()

    user_done_exercise_ids = set(user_exercises_details_df['id'])
    recommended_exercises = recommended_exercises[
        ~recommended_exercises['id'].isin(user_done_exercise_ids)
    ]

    recommendations = recommended_exercises['id'].tolist()

    if not recommendations and not all_exercises_df.empty:
        print(f"User {user_id} has done all exercises for {most_common_muscle_group}. Returning top 5 overall as fallback.")
        fallback_recs = all_exercises_df[~all_exercises_df['id'].isin(user_done_exercise_ids)]
        return fallback_recs.head(5)['id'].tolist()
    elif not recommendations:
        return []

    print(f"Recommendations for user {user_id}: {recommendations[:10]}")
    return recommendations[:10]

# --- Recommendation Endpoint ---
@app.route('/recommendations/<user_id>', methods=['GET'])
def get_recommendations(user_id):
    print(f"Received request for user_id: {user_id}")
    if not user_id:
        return jsonify({"error": "User ID is required"}), 400

    all_exercises_df = fetch_all_exercises()
    user_workout_exercises_df, user_exercises_details_df = fetch_user_history(user_id)

    if all_exercises_df.empty:
        print("Error: Could not fetch master exercise list from Supabase.")
        return jsonify({"error": "Could not retrieve exercise data. Cannot generate recommendations."}), 500

    recommended_ids = generate_simple_content_recommendations(
        user_id,
        user_workout_exercises_df,
        user_exercises_details_df,
        all_exercises_df
    )

    if not recommended_ids:
        print(f"No recommendations could be generated for user {user_id}.")
        return jsonify({"message": "No specific recommendations available at this time.", "recommendations": []}), 200

    return jsonify({"recommendations": recommended_ids})

if __name__ == '__main__':
    app.run(debug=True)  # debug=True for development only
