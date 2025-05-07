# heronfit-recommendation-service

Backend service for HeronFit workout recommendations, providing personalized and community-driven exercise suggestions.

## Project Overview

This service leverages user workout history and exercise data stored in Supabase to generate tailored workout template recommendations. It offers both content-based suggestions (Full Body, Push, Pull, Legs) and collaborative filtering-based suggestions (Popular with Others, Popular This Week, Popular This Month).

## Environment Variables

To run this application, you need to set up a `.env` file in the root directory with the following environment variables:

```env
SUPABASE_URL="your_supabase_url"
SUPABASE_SERVICE_KEY="your_supabase_service_key"
```

Replace `"your_supabase_url"` and `"your_supabase_service_key"` with your actual Supabase project credentials.

## Installation

### Local Development

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/heronfit-recommendation-service.git
    cd heronfit-recommendation-service
    ```
2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv venv
    # On Windows
    venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
    ```
3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Set up your `.env` file** as described in the [Environment Variables](#environment-variables) section.

### Docker

1.  **Build the Docker image:**
    ```bash
    docker build -t heronfit-recommendation-service .
    ```
2.  Ensure you have a `.env` file present in the root directory when running the container, or provide environment variables directly to the `docker run` command.

## Usage

### Local Development

1.  **Run the Flask development server:**
    ```bash
    python app.py
    ```
2.  The service will be available at `http://127.0.0.1:5000`.

### Docker

1.  **Run the Docker container:**
    ```bash
    # Make sure your .env file is in the current directory or use -e flags
    docker run -p 8080:8080 --env-file .env heronfit-recommendation-service
    ```
2.  The service will be available at `http://localhost:8080`.

## API Endpoints

### Get Workout Recommendations

- `GET /recommendations/workout/<user_id>`

  - **Description:** Fetches workout template recommendations for a given user.
  - **Path Parameter:**
    - `user_id`: (string, required) The ID of the user.
  - **Example:** `GET /recommendations/workout/some-user-uuid`
  - **Response:** A JSON object containing two lists of recommended workout templates:
    - `for_you_recommendations`: Content-based recommendations (e.g., Full Body, Push, Pull, Legs).
    - `community_recommendations`: Collaborative filtering-based recommendations (e.g., Popular With Others, Popular This Week, Popular This Month).
      Each template includes `template_name`, `focus`, and a list of `exercise_ids`.

  ```json
  {
    "for_you_recommendations": [
      {
        "template_name": "Recommended Full Body",
        "focus": "General Full Body",
        "exercises": ["exercise_uuid_1", "exercise_uuid_2", "..."]
      }
    ],
    "community_recommendations": [
      {
        "template_name": "Popular This Week",
        "focus": "Trending Weekly",
        "exercises": ["exercise_uuid_3", "exercise_uuid_4", "..."]
      }
    ]
  }
  ```

## Technologies Used

- **Python**: 3.11
- **Flask**: Web framework
- **Gunicorn**: WSGI HTTP Server for production
- **Pandas**: Data manipulation and analysis
- **Supabase (Python Client)**: Backend-as-a-Service for database interactions
- **python-dotenv**: Environment variable management
- **Docker**: Containerization
