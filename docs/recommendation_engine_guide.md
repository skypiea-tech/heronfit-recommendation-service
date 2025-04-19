# HeronFit Recommendation Engine Development Guide

**Version:** 1.0
**Date:** April 19, 2025

## 1. Overview

This document outlines the development plan and guidelines for the HeronFit recommendation engine, a separate backend service designed to provide personalized workout and exercise suggestions to users based on their history and exercise characteristics.

This service adheres to the principles outlined in the main HeronFit Comprehensive AI Development Guidelines (Section 11), emphasizing a backend-focused approach for recommendation logic.

## 2. Architecture

- **Service Type:** Standalone Backend Service (Python with Flask/FastAPI recommended).
- **Deployment:** Containerized (Docker) deployment to a cloud platform or potentially Supabase Edge Functions _only if logic remains very simple_.
- **Communication:** Provides a RESTful API endpoint for the HeronFit Flutter application to consume.
- **Database:** Securely connects to the existing HeronFit Supabase PostgreSQL database.

## 3. Core Requirements (Based on Project Charter & Guidelines)

- Implement both **Content-Based Filtering** and **Collaborative Filtering**.
- Develop a **Hybrid Approach** combining the strengths of both methods.
- Provide recommendations for **full workout templates**, each consisting of a coherent set of exercises (e.g., 5-9 exercises per template).
- Integrate with user profile data (goals, fitness level - if available) to enhance recommendations, especially for beginners and for tailoring template structure.
- Allow for future enhancements like user feedback loops.

## 4. Technology Stack

- **Language:** Python 3.x
- **Web Framework:** Flask or FastAPI
- **Data Manipulation:** Pandas
- **Machine Learning:** Scikit-learn (for TF-IDF, Cosine Similarity, SVD, etc.)
- **Database Client:** `supabase-py`
- **Environment Variables:** `python-dotenv`

## 5. Data Requirements

The service needs secure read access to the following Supabase tables (referencing provided schema):

- `users`: User IDs, potentially profile information (goals, fitness level - `goal`, `weight`, `height`, `gender`).
- `workouts`: User's workout sessions (linking `user_id` to workout instances).
- `workout_exercises`: Links `workouts` (`workout_id`) to specific `exercises` (`exercise_id`) performed, including `order_index`.
- `exercise_sets`: Details of sets performed (`reps`, `weight_kg`, `completed`, `set_number`) for each `workout_exercise_id`.
- `exercises`: Master list of exercises, including properties like:
  - `id`
  - `name`
  - `primaryMuscles` (JSONB - primary muscle group(s))
  - `secondaryMuscles` (JSONB)
  - `equipment` (text)
  - `level` (text - e.g., beginner, intermediate)
  - `category` (text - e.g., strength, cardio)
  - `force` (text - e.g., push, pull)
  - `mechanic` (text - e.g., compound, isolation)
  - `instructions` (JSONB)
  - `images` (JSONB)
  - (Ensure these properties are populated).

**Security:** Use the Supabase **Service Role Key** for backend access, stored securely in environment variables (`.env`). **Do not expose this key client-side.**

## 6. Implementation Steps

1.  **Project Setup:**
    - Initialize Python project (virtual environment, install dependencies).
    - Set up Flask/FastAPI application structure.
    - Configure Supabase client using environment variables.
2.  **Data Fetching Module:**
    - Create functions to securely fetch and potentially preprocess data from Supabase tables (user history, exercise details).
    - Use Pandas DataFrames for efficient manipulation.
3.  **Content-Based Filtering Module:**
    - **Feature Extraction:** Represent exercises based on their properties (`primaryMuscles`, `equipment`, `level`, `category`, etc.).
    - **User Profile:** Build a profile of user preferences based on the features of exercises/workouts they've completed frequently/recently. Consider workout structure (e.g., muscle group splits).
    - **Template Generation/Scoring:** Develop logic to assemble or score potential workout templates based on similarity to the user profile, ensuring variety, appropriate difficulty (`level`), and target muscle groups (`primaryMuscles`). Aim for 5-9 exercises per template.
4.  **Collaborative Filtering Module:**
    - **User-Item Matrix:** Construct a matrix representing user interactions. Items could be individual exercises _or_ potentially implicitly defined workout patterns if identifiable. Handle sparsity.
    - **Algorithm Choice:**
      - **Memory-Based:** Find users with similar workout histories/patterns. Recommend templates based on what similar users do.
      - **Model-Based:** Use Matrix Factorization (e.g., SVD) to predict user affinity for exercises _within the context of generating a full template_.
    - **Template Generation/Recommendation:** Generate coherent workout templates based on predicted exercise affinities or similar users' successful templates.
5.  **Hybrid Approach Module:**
    - Combine results from content-based and collaborative filtering to generate/rank workout templates.
    - Strategies: Weighted scoring of templates, using one method to generate candidates and another to rank, feature combination.
6.  **API Endpoint:**
    - Create a REST API endpoint (e.g., `GET /recommendations/workout/{user_id}`).
    - Input: User ID.
    - Output: JSON representing one or more recommended workout templates. Each template should contain a list of exercise IDs (ordered appropriately if possible) and potentially metadata (e.g., template name, focus). Example: `{"recommendations": [{"template_name": "Push Day Beginner", "focus": "Chest, Shoulders, Triceps", "exercises": ["exercise_id_1", "exercise_id_5", ...]}]}`
    - Handle request validation and error responses.
7.  **Testing:**
    - Implement unit tests for individual modules (data fetching, filtering logic).
    - Update tests to validate template generation.
    - Consider integration tests for the API endpoint.
8.  **Deployment:**
    - Containerize the application using Docker.
    - Deploy to a suitable cloud platform (e.g., Heroku, Google Cloud Run, AWS Fargate) or investigate Supabase Edge Functions if feasible.

## 7. Flutter Integration (Reminder)

- The Flutter app will:
  - Make an HTTP request to the deployed recommendation API endpoint, passing the user ID.
  - Receive a JSON object containing one or more workout templates (each with a list of exercise IDs).
  - Fetch the full details for all exercise IDs within the chosen/displayed template(s) from Supabase using its standard client.
  - Display the recommended workout template(s) in the UI, potentially allowing the user to start the workout.

## 8. Future Considerations

- Incorporating explicit user feedback (ratings, like/dislike).
- Handling cold-start problem (new users/new exercises).
- Re-training models periodically.
- A/B testing different algorithms.
- Recommending full workout plans.
- Workout Template Refinement.
