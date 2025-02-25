import requests
from src.environment.initialize_environment import environment_info


class User:
    def __init__(self, token):
        self.token = (token or '').split(" ")[-1]
        self.bearer_token = f"Bearer {self.token}"
        self.authenticated = self.authenticate()

    def authenticate(self):
        headers = {
            "Authorization": self.bearer_token,
            "Content-Type": "application/json",
        }
        response = requests.get(environment_info.DS_APP_API_URL + "/api/v1/ds-app-auth", headers=headers)
        if response.status_code == 200:
            return True

        return False
