from slack_sdk import WebClient
from src.environment.initialize_environment import environment_info


def send_slack_message(message, subject, channel):
    slack_token = environment_info.SLACK_CHANNEL_TOKEN
    client = WebClient(token=slack_token)
    client.chat_postMessage(
        channel=channel, text=f"*{subject}* \n{message}", username=channel
    )


def send_slack_message_by_env(message, env, subject):
    if env == "prod":
        channel = "ds-mon-alert"
    else:
        channel = "ds-mon-alert-dev"

    send_slack_message(message, subject, channel)
