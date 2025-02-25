# Data Science Apps

## Structure
The projects are divided into 2 layers:
- Backend (API and background scripts)
- Frontend (Streamlit application)

## Local Setup
### Backend Setup

```commandline
    python -m venv venv # Create a venv with python 3.11
    pip install -r requirements.txt
    # Copy over the .env (the required environment variables are documented in initialize_environment.py)
    # The following commands need to be executed from 3 separate terminals
    python -m src.scripts.tunnel # Start the ssh tunnel
    python -m src.scripts.run_query # Start the run_query.py
    python -m src.utils.save_plots_and_table # Start the save_plots_and_table.py
    python -m src.api.start_uvicorn # Starting the API server
```

### Frontend (Streamlit) Setup
```commandline
    streamlit run deploy_streamlit_app.py
```

### API Documentation
API documentation can be accessed on the /docs route. If the API is running on localhost:8080, then access the docs
from localhost:8080/docs
