import os
import re
import datetime
from peewee import *
from playhouse.postgres_ext import *
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv
import sentry_sdk

load_dotenv()

print("init sentry...")
sentry_sdk.init(
    dsn=os.getenv("SENTRY_URL"),
    # Add data like request headers and IP for users,
    # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
    send_default_pii=False,
    enable_logs=True,
)
# Initializes your app with your bot token and socket mode handler
sentry_sdk.logger.info("starting bot")
app = App(token=os.getenv("SLACK_BOT_TOKEN"))
COMMIT_ID = os.getenv("SOURCE_COMMIT")

db = PostgresqlExtDatabase(os.getenv("DATABASE_URL"))

class BaseModel(Model):
    """All models inherit this to share the database connection."""
    class Meta:
        database = db
class User(BaseModel):
    id = AutoField()
    username = TextField(default="")
    user_id = TextField(unique=True)
    trouted_count = IntegerField(default=0)
    trouter_count = IntegerField(default=0)
    timestamp = DateTimeField(
        default=datetime.datetime.now,
        index=True)
    unsubscribed = BooleanField(default=False)
class Trout(BaseModel):
    id = AutoField()
    target = TextField()
    actor = TextField()
    reason = TextField(default="")
    timestamp = DateTimeField(
        default=datetime.datetime.now,
        index=True)

print("Connecting to database")
db.connect()
print("Creating tables")
db.create_tables([Trout, User])
print("Done")

TROUT_HELP = f"*:trouted: Troutpheus commands*\n\n`/trout @USER [REASON]` - Tells the user they made a mistake\n`/trout-leaderboard` - Posts the top 10 trouted users and whackers\n`/trout-count @USER` - Posts how many times you got trouted and whacked others\n`/trout-user-logs @USER` - Posts the last 10 trouts of a user\n\nTrout logs: <#{os.getenv("TROUT_LOGS_CHANNEL")}>\nFor support, DM @normalperson543 or drop a message in that channel :p"

username_pattern = r"^<@[UW][A-Z0-9]{8,11}(?:\|[a-z0-9._-]+)?>"
username_pat = re.compile(username_pattern)

@app.command("/trout")
def respond_t(ack, command, client, body, respond, say):
    # Acknowledge command request
    ack()
    sentry_sdk.logger.info(f"responding to trouting req from {body["user_id"]} in {body["channel_id"]}")

    split_command = command["text"].split(" ")
    pattern = r"^<https:\/\/[\w-]+\.slack\.com\/archives\/([CGD][A-Z0-9]+)\/p(\d+)>$"
    reason = ""
    pat = re.compile(pattern)
    if split_command[0] == "":
        sentry_sdk.logger.info(f"no user passed in, responding with help")
        respond(
            text=TROUT_HELP
        )
        exit()
    elif len(split_command) == 1:
        sentry_sdk.logger.info(f"no reason passed in, responding with reason error")
        respond(
            text=":trouted: *Whack!* You should enter a reason to why you're whacking this user. The syntax for trouting someone is `/trout @USER [REASON]`."
        )
        exit()
    elif not re.match(pat, split_command[1]):
        reason = " ".join(split_command[1:])
        if len(reason) > 100:
            sentry_sdk.logger.info(f"reason too long")
            respond(f":trouted: *Whack!* Your reason can't be over 100 characters (it is {len(reason)} characters long). Please edit it so your reason is <= 100 characters.\n\nYou said: ```{reason}```")
            exit()
    else:
        reason = split_command[1][1:-1]
    if not re.match(username_pat, split_command[0]):
        sentry_sdk.logger.info(f"attempted to trout {split_command[0]} but it is not a valid user")
        respond(":trouted: *Whack!* That's not a valid user. The syntax for trouting someone is `/trout @USER [REASON]`.")
        exit()
    target_id = split_command[0][2:]
    target_id = target_id[:target_id.index("|")]
    actor_id = body["user_id"]

    sentry_sdk.logger.info(f"target {target_id} trouted by actor {actor_id}")

    actor, created_actor = User.get_or_create(user_id=actor_id)
    if len(actor.username) == 0:
        slack_user = client.users_info(user=actor_id)
        actor.username = slack_user["user"]["name"]
        sentry_sdk.logger.info(f"actor new username: {actor.user_id} --> {actor.username}")
    actor.trouter_count += 1
    actor.save()

    target, created_target = User.get_or_create(user_id=target_id)
    if len(target.username) == 0:
        slack_user = client.users_info(user=target_id)
        target.username = slack_user["user"]["name"]
        sentry_sdk.logger.info(f"target new username: {target.user_id} --> {actor.username}")
    target.trouted_count += 1
    target.save()

    
    respond(
        response_type="in_channel",
        text=f"{target.username} has been *whacked* by a wet trout :3\n\nDon't take this too seriously. Someone just wants to let you know that you did something silly.\nReason: {reason}",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Whack!* *@{target.username}* (:trouted:{target.trouted_count}) has been *whacked* by a wet trout :3\n\n\nDon't take this too seriously. Someone just wants to let you know that you did something silly.\n>{reason}"
                },
                "accessory": {
                    "type": "image",
                    "image_url": "https://user-cdn.hackclub-assets.com/019d711a-37ab-7422-a375-b7bcd3629304/Rainbow_trout_transparent.png",
                    "alt_text": "rainbow trout"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"whacker: *@{actor.username}* (:trouted:{actor.trouted_count}) | `/trout @user [reason]` | <#{os.getenv("TROUT_LOGS_CHANNEL")}>"
                    }
                ]
            }
        ]
    )

    Trout.create(target=target_id, actor=actor_id, reason=reason)

    if not target.unsubscribed:
        dm_resp = app.client.conversations_open(users=target_id)
        dm_channel_id = dm_resp["channel"]["id"]
        client.chat_postMessage(
            channel=dm_channel_id,
            text=f"Whack! You've just been whacked with a wet trout by <@{actor.user_id}> :3 Don't take this too seriously. Someone just wants to let you know that you did something silly. Reason: {reason}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Whack!* You've just been *whacked* with a wet trout by <@{actor.user_id}> :3\n\nDon't take this too seriously. Someone just wants to let you know that you did something silly. <{os.getenv("SUPPORT_CANVAS")}|What's a trout?>\n>{reason}"
                    },
                    "accessory": {
                        "type": "image",
                        "image_url": "https://user-cdn.hackclub-assets.com/019d711a-37ab-7422-a375-b7bcd3629304/Rainbow_trout_transparent.png",
                        "alt_text": "rainbow trout"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Unsubscribe from trout DMs",
                            },
                            "style": "danger",
                            "value": "unsub_button",
                            "action_id": "unsub_button"
                        }
                    ]
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"you've been trouted {target.trouted_count} times and trouted {target.trouter_count} others | <#{os.getenv("TROUT_LOGS_CHANNEL")}>"
                        }
                    ]
                }
            ],
            unfurl_links=False
        )
    client.chat_postMessage(
        channel=os.getenv("TROUT_LOGS_CHANNEL"),
        text=f":trouted: *{target.username}* ({target.user_id}) (:trouted:{target.trouted_count}) was *whacked* by *{actor.username}* ({actor.user_id}) (:trouted:{actor.trouted_count}) with a wet trout\n\n>{reason}",
        unfurl_links=False
    )

@app.command("/trout-leaderboard")
def respond_tl(ack, body, respond):
    ack()
    sentry_sdk.logger.info(f"responding to leaderboard req from {body["user_id"]} in {body["channel_id"]}")
    out = "*:trouted: Top Trouted*\n"
    index = 1
    for user in User.select().order_by(User.trouted_count.desc()).limit(10):
        out += f"{index}. *{user.username}* ({user.user_id}) - `{user.trouted_count}`\n"
        index += 1
    out += "\n*:trouted: Top Whackers*\n"
    index = 1
    for user in User.select().order_by(User.trouter_count.desc()).limit(10):
        out += f"{index}. *{user.username}* ({user.user_id}) - `{user.trouter_count}`\n"
        index += 1
    respond(
        response_type="in_channel",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": out
                }
            }
	    ]
    )

@app.command("/trout-count")
def respond_tc(ack, respond, body, command):
    ack()
    sentry_sdk.logger.info(f"responding to trout count req from {body["user_id"]} in {body["channel_id"]}")
    split_command = command["text"].split(" ")
    if split_command[0] == "":
        sentry_sdk.logger.info("no user passed in for trout count req, responding with help")
        respond(
            text=TROUT_HELP
        )
        exit()
    
    if not re.match(username_pat, split_command[0]):
        sentry_sdk.logger.info(f"attempted to get stats for {split_command[0]} but it is not a valid user")
        respond(":trouted: *Whack!* That's not a valid user. The syntax for getting someone's trout count is `/trout-count @USER`.")
        exit()
    target_id = split_command[0][2:]
    target_id = target_id[:target_id.index("|")]
    sentry_sdk.logger.info(f"identified the stat req for {target_id}")
    received_user = User.get(user_id=target_id)
    respond(
        response_type="in_channel",
        text = f":trouted: *{received_user.username}* ({received_user.user_id}) has been trouted `{received_user.trouted_count}` times and trouted others `{received_user.trouter_count}` times."
    )

@app.action("unsub_button")
def unsub(ack, body, say):
    ack()
    sentry_sdk.logger.info(f"responding to unsub req from {body["user"]["id"]} in {body["channel"]["id"]}")
    target_id=body["user"]["id"]
    user = User.get(user_id=target_id)
    user.unsubscribed = True
    user.save() 
    say(
        response_type="in_channel",
        text="You've successfully unsubscribed from getting DMs about you being trouted.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":red-x: You've successfully unsubscribed from getting DMs about you being trouted."
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Resubscribe to trout DMs",
                        },
                        "style": "primary",
                        "value": "resub_button",
                        "action_id": "resub_button"
                    }
                ]
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"<#{os.getenv("TROUT_LOGS_CHANNEL")}>"
                    }
                ]
            }
        ]
    )
@app.action("resub_button")
def resub(ack, body, say):
    ack()
    sentry_sdk.logger.info(f"responding to resub req from {body["user"]["id"]} in {body["channel"]["id"]}")
    target_id=body["user"]["id"]
    user = User.get(user_id=target_id)
    user.unsubscribed = False
    user.save()
    dm_resp = app.client.conversations_open(users=target_id)
    dm_channel_id = dm_resp["channel"]["id"]
    say(
        response_type="in_channel",
        text="You've successfully resubscribed to getting DMs about you being trouted.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":white_check_mark: You've successfully resubscribed to getting DMs about you being trouted."
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Unsubscribe from trout DMs",
                        },
                        "style": "danger",
                        "value": "unsub_button",
                        "action_id": "unsub_button"
                    }
                ]
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"<#{os.getenv("TROUT_LOGS_CHANNEL")}>"
                    }
                ]
            }
        ]
    )

@app.command("/trout-user-log")
def respond_tul(ack, command, respond, body):
    ack()
    sentry_sdk.logger.info(f"responding to trout user log req from {body["user_id"]} in {body["channel_id"]}")
    split_command = command["text"].split(" ")
    if split_command[0] == "":
        sentry_sdk.logger.info("no user passed in for trout user log req, responding with help")
        respond(
            text=TROUT_HELP
        )
        exit()
    
    if not re.match(username_pat, split_command[0]):
        sentry_sdk.logger.info(f"attempted to get user log for {split_command[0]} but it is not a valid user")
        respond(":trouted: *Whack!* That's not a valid user. The syntax for getting someone's trout count is `/trout-count @USER`.")
        exit()
    target_id = split_command[0][2:]
    target_id = target_id[:target_id.index("|")]
    sentry_sdk.logger.info(f"identified the user log req for {target_id}")
    received_user = User.get(user_id=target_id)
    trouted_out = f"*:trouted: Trout user log*\nFor <@{received_user.user_id}> ({received_user.user_id}) (trouted by `{received_user.trouted_count}`, trouted `{received_user.trouter_count}` others) - last 10 trouts\n\n"
    for trout in Trout.select().where(Trout.target == split_command[0][2:13]).order_by(Trout.timestamp.desc()).limit(10):
        timestamp = trout.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        trouted_out += f"- *{timestamp}*: <@{trout.target}> *whacked* by a wet trout by <@{trout.actor}>: {trout.reason}\n"
    sentry_sdk.logger.info(f"finished getting the user log stats for {target_id}")
    respond(
        text = trouted_out,
        unfurl_links=False
    )

# Start your app
if __name__ == "__main__":
    SocketModeHandler(app, os.getenv("SLACK_API_TOKEN")).start()