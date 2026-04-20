import os
import re
import datetime
from peewee import *
from playhouse.postgres_ext import *
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv
import sentry_sdk
from slack_sdk.errors import SlackApiError


load_dotenv()

print("init sentry...")
sentry_sdk.init(
    dsn=os.getenv("SENTRY_URL"),
    # Add data like request headers and IP for users,
    # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
    send_default_pii=False,
    enable_logs=True,
    environment=os.getenv("ENVIRONMENT")
)
# Initializes your app with your bot token and socket mode handler
sentry_sdk.logger.info("starting bot")
app = App(token=os.getenv("SLACK_BOT_TOKEN"))

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
class BlacklistedChannel(BaseModel):
    id = AutoField()
    channel = TextField(unique=True)
    timestamp = DateTimeField(
        default=datetime.datetime.now,
        index=True)

print("Connecting to database")
db.connect()
print("Creating tables")
db.create_tables([Trout, User, BlacklistedChannel])
print("Done")

TROUT_HELP = f"*:trouted: Troutpheus commands*\n\n`/trout @USER [REASON]` - Tells the user they made a mistake\n`/trout-leaderboard` - Posts the top 10 trouted users and whackers\n`/trout-count @USER` - Posts how many times you got trouted and whacked others\n`/trout-user-logs @USER` - Posts the last 10 trouts of a user\n`/trout-blacklist #[CHANNEL NAME]` - Blocks Troutpheus from sending messages into your channel (channel manager required)\n`/trout-whitelist #[CHANNEL NAME]` - Allows Troutpheus to send messages to your channel (channel manager required)\n\nTrout logs: <#{os.getenv("TROUT_LOGS_CHANNEL")}>\nFor support, DM @normalperson543 or drop a message in that channel :p"
BLACKLIST_USERS = os.getenv("BLACKLIST_USERS").split(",")

username_pattern = r"^<@[UW][A-Z0-9]{8,11}(?:\|[a-z0-9._-]+)?>"
username_pat = re.compile(username_pattern)

channel_id_pattern = r"^<#([C][A-Z0-9]{8,10})(\|[a-z0-9_-]+)?>$"
channel_id_pat = re.compile(channel_id_pattern)

def trout(actor_id, target_id, reason, client, respond, channel_id="", send_using_respond=True, actor_dm_id=""):
    if actor_id in BLACKLIST_USERS:
        sentry_sdk.logger.info(f"{actor_id} is banned")
        respond("You have been banned from using Troutpheus due to abuse.")
        exit()
    
    last_actor_trout = Trout.select().where(Trout.actor == actor_id).order_by(Trout.timestamp.desc()).first()
    current_time = datetime.datetime.now()
    
    if last_actor_trout:
        time_difference = current_time - last_actor_trout.timestamp
        time_difference_seconds = time_difference.total_seconds()
        if time_difference_seconds < float(os.getenv("ACTOR_RATE_LIMIT")):
            sentry_sdk.logger.warning(f"{actor_id} encountered an actor rate limit ({time_difference_seconds} seconds)")
            respond(f":trouted: *Whack!* It looks like you need to slow down between trouting people. Please wait some time, then whack <@{target_id}> again.\nHere's the reason that you whacked them:```{reason}```")
            exit()

    last_target_trout = Trout.select().where(Trout.target == target_id).order_by(Trout.timestamp.desc()).first()
    if last_target_trout:
        time_difference = current_time - last_target_trout.timestamp
        time_difference_seconds = time_difference.total_seconds()
        if time_difference_seconds < float(os.getenv("TARGET_RATE_LIMIT")):
            sentry_sdk.logger.warning(f"{actor_id} encountered a target rate limit ({time_difference_seconds} seconds)")
            respond(f":trouted: *Whack!* It looks like <@{target_id}> has been trouted relatively recently! Please wait some time, then whack them again.\nHere's the reason that you whacked them:```{reason}```")
            exit()

    if len(channel_id) > 0:
        sentry_sdk.logger.info(f"target {target_id} trouted by actor {actor_id} in {channel_id}")
    else:
        sentry_sdk.logger.info(f"target {target_id} trouted by actor {actor_id} (no channel ID)")
    sentry_sdk.metrics.count(
        "trout",
        1,
        attributes={
            "target": target_id,
            "actor": actor_id,
            "channel_id": channel_id
        },
    )

    reason = reason.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    actor, created_actor = User.get_or_create(user_id=actor_id)
    if len(actor.username) == 0:
        slack_user = client.users_info(user=actor_id)
        actor.username = slack_user["user"]["real_name"]
        sentry_sdk.logger.info(f"actor new username: {actor.user_id} --> {actor.username}")
    

    target, created_target = User.get_or_create(user_id=target_id)
    if len(target.username) == 0:
        slack_user = client.users_info(user=target_id)
        target.username = slack_user["user"]["real_name"]
        sentry_sdk.logger.info(f"target new username: {target.user_id} --> {target.username}")
    
    actor.trouter_count += 1
    actor.save()

    target.trouted_count += 1
    target.save()

    Trout.create(target=target_id, actor=actor_id, reason=reason)

    if not target.unsubscribed:
        try:
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
                                    "text": "Whack them back",
                                },
                                "style": "primary",
                                "value": actor_id,
                                "action_id": "troutback_button"
                            },
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
                                "text": f"you've been trouted {target.trouted_count} times and trouted {target.trouter_count} others | `/trout @[USER] [REASON]` | <#{os.getenv("TROUT_LOGS_CHANNEL")}>"
                            }
                        ]
                    }
                ],
                unfurl_links=False
            )
        except SlackApiError:
            sentry_sdk.logger.warning("cannot send message to bot")
            
    if send_using_respond:
        respond(
            response_type="ephemeral" if is_blacklisted(channel_id) else "in_channel",
            text=f"Whack! {target.username} has been *whacked* by a wet trout :3\n\nDon't take this too seriously. Someone just wants to let you know that you did something silly.\nReason: {reason}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Whack!* <@{target.user_id}> (:trouted:{target.trouted_count}) has been *whacked* by a wet trout :3\n\n\nDon't take this too seriously. Someone just wants to let you know that you did something silly.\n>{reason}"
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
                            "text": f"whacker: <@{actor.user_id}> (:trouted:{actor.trouted_count}) | `/trout @[USER] [REASON]` | <#{os.getenv("TROUT_LOGS_CHANNEL")}>"
                        }
                    ]
                }
            ]
        )
    else:
        client.chat_postMessage(
            channel=actor_dm_id,
            text=f"You whacked {target.username} with a wet trout :3 Reason: {reason}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Whack!* You *whacked* <@{target.user_id}> (:trouted:{target.trouted_count}) by a wet trout :3\n>{reason}"
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
                            "text": f"whacker: <@{actor.user_id}> (:trouted:{actor.trouted_count}) | `/trout @[USER] [REASON]` | <#{os.getenv("TROUT_LOGS_CHANNEL")}>"
                        }
                    ]
                }
            ]
        )

    client.chat_postMessage(
        channel=os.getenv("TROUT_LOGS_CHANNEL"),
        text=f":siren1: *{target.username}* ({target.user_id}) (:trouted:{target.trouted_count}) was *whacked* by *{actor.username}* ({actor.user_id}) (:trouted:{actor.trouted_count}) with a wet trout\n\n>{reason}",
        unfurl_links=False
    )

def is_blacklisted(channel_id):
    return BlacklistedChannel.select().where(BlacklistedChannel.channel == channel_id).count() > 0
@app.command("/trout")
def respond_t(ack, command, body, respond, client):
    # Acknowledge command request
    ack()
    sentry_sdk.logger.info(f"responding to trouting req from {body["user_id"]} in {body["channel_id"]}")

    split_command = command["text"].split(" ")
    reason = ""
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
    reason = " ".join(split_command[1:])
    if len(reason) > 200:
        sentry_sdk.logger.info(f"reason too long")
        respond(f":trouted: *Whack!* Your reason can't be over 200 characters (it is {len(reason)} characters long). Please edit it so your reason is <= 200 characters.\n\nYou said: ```{reason}```")
        exit()
    if not re.match(username_pat, split_command[0]):
        sentry_sdk.logger.info(f"attempted to trout {split_command[0]} but it is not a valid user")
        respond(":trouted: *Whack!* That's not a valid user. The syntax for trouting someone is `/trout @USER [REASON]`.")
        exit()
    target_id = split_command[0][2:]
    target_id = target_id[:target_id.index("|")]
    actor_id = body["user_id"]

    trout(actor_id, target_id, reason, client, respond, body["channel_id"])
    

@app.command("/trout-leaderboard")
def respond_tl(ack, body, respond):
    ack()
    sentry_sdk.metrics.count(
        "trout_leaderboard",
        1,
        attributes={
            "channel_id": body["channel_id"],
            "actor": body["user_id"]
        },
    )
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
        response_type="ephemeral" if is_blacklisted(body["channel_id"]) else "in_channel",
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
    sentry_sdk.metrics.count(
        "trout_count",
        1,
        attributes={
            "channel_id": body["channel_id"],
            "actor": body["user_id"],
            "target": target_id
        },
    )
    try:
        received_user = User.get(user_id=target_id)
    except User.DoesNotExist:
        sentry_sdk.logger.info(f"cannot find user {target_id}")
        respond(
            text = "*Whack!* The user you entered hasn't used Troutpheus yet. Check the username you entered, and try again. For reference, the correct syntax is `/trout-count @[USER]`."
        )
        exit()
    respond(
        response_type="ephemeral" if is_blacklisted(body["channel_id"]) else "in_channel",
        text = f":trouted: *{received_user.username}* ({received_user.user_id}) has been trouted `{received_user.trouted_count}` times and trouted others `{received_user.trouter_count}` times."
    )


@app.action("troutback_button")
def troutback_modal_open(ack, body, client, action):
    ack()
    sentry_sdk.logger.info(f"responding to troutback button press from {body["user"]["id"]} to {action["value"]}")
    action = body["actions"][0]

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "private_metadata": action["value"],
            "title": {
                "type": "plain_text",
                "text": "Trout someone back >:3",
                "emoji": True
            },
            "callback_id": "troutback",
            "submit": {
                "type": "plain_text",
                "text": "Trout them :devious-ahh:",
                "emoji": True
            },
            "type": "modal",
            "close": {
                "type": "plain_text",
                "text": "nah i change my mind",
                "emoji": True
            },
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*You're about to whack <@{action["value"]}> back with a trout!* Enter the reason why you're trouting them back."
                    }
                },
                {
                    "type": "input",
                    "block_id": "reason_block",
                    "element": {
                        "type": "plain_text_input",
                        "multiline": True,
                        "action_id": "reason_input"
                    },
                    "label": {
                        "type": "plain_text",
                        "text": "Trout reason",
                        "emoji": True
                    },
                    "optional": False
                }
            ]
        }
    )

@app.view("troutback")
def handle_troutback_submit(ack, body, view, respond, client):
    ack()

    dm_resp = app.client.conversations_open(users=body["user"]["id"])
    dm_channel_id = dm_resp["channel"]["id"]

    target_id = view["private_metadata"]
    

    reason = view["state"]["values"]["reason_block"]["reason_input"]["value"]
    sentry_sdk.logger.info(f"responding to troutback submission from {body["user"]["id"]} to {target_id}")
    if len(reason) == 0:
        sentry_sdk.logger.info(f"no reason passed in for troutback, responding with reason error")
        client.chat_postMessage(
            channel=dm_channel_id,
            text=":trouted: *Whack!* You should enter a reason to why you're whacking this user. The syntax for trouting someone is `/trout @USER [REASON]`."
        )
        exit()
    if len(reason) > 200:
        sentry_sdk.logger.info(f"reason too long for troutback")
        client.chat_postMessage(
            channel=dm_channel_id,
            text=f":trouted: *Whack!* Your reason can't be over 200 characters (it is {len(reason)} characters long). Please edit it so your reason is <= 200 characters.\n\nYou said: ```{reason}```"
        )
        exit()
    trout(body["user"]["id"], target_id, reason, client, respond, "", False, dm_channel_id)
    

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
    sentry_sdk.metrics.count(
        "trout_user_log",
        1,
        attributes={
            "channel_id": body["channel_id"],
            "actor": body["user_id"],
            "target": target_id
        },
    )
    try:
        received_user = User.get(user_id=target_id)
    except User.DoesNotExist:
        sentry_sdk.logger.info(f"cannot find user {target_id}")
        respond(
            text = "*Whack!* The user you entered hasn't used Troutpheus yet. Check the username you entered, and try again. For reference, the correct syntax is `/trout-user-log @[USER]`."
        )
        exit()
    trouted_out = f"*:trouted: Trout user log*\nFor <@{received_user.user_id}> ({received_user.user_id}) (trouted by `{received_user.trouted_count}`, trouted `{received_user.trouter_count}` others) - last 10 trouts\n\n*Trouted by others*\n\n"
    for trout in Trout.select().where(Trout.target == split_command[0][2:13]).order_by(Trout.timestamp.desc()).limit(10):
        timestamp = trout.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        trouted_out += f"- *{timestamp}*: <@{trout.target}> *whacked* by a wet trout by <@{trout.actor}>: {trout.reason}\n"
    trouted_out += "\n\n*Trouted others*\n\n"
    for trout in Trout.select().where(Trout.actor == split_command[0][2:13]).order_by(Trout.timestamp.desc()).limit(10):
        timestamp = trout.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        trouted_out += f"- *{timestamp}*: <@{trout.target}> *whacked* by a wet trout by <@{trout.actor}>: {trout.reason}\n"
    sentry_sdk.logger.info(f"finished getting the user log stats for {target_id}")
    respond(
        text = trouted_out,
        unfurl_links=False
    )
@app.command("/trout-blacklist")
def respond_blacklist(ack, respond, body, client, command):
    ack()
    sentry_sdk.logger.info(f"responding to trout blacklist from {body["user_id"]}")
    split_command = command["text"].split(" ")
    if not re.match(channel_id_pat, split_command[0]):
        sentry_sdk.logger.info(f"attempted to blacklist {body["channel_id"]} but it is not valid")
        respond(":trouted: *Whack!* The channel you tried to blacklist isn't valid. The correct syntax is `/trout-blacklist #[CHANNEL NAME]`.")
        exit()
    target_id = split_command[0][2:]
    try:
        target_id = target_id[:target_id.index("|")]
    except ValueError:
         target_id = target_id[:target_id.index(">")]
    sentry_sdk.logger.info(f"identified the blacklist req for {target_id}")

    try:
        members_response = client.conversations_members(channel=target_id)
    except SlackApiError:
        sentry_sdk.logger.info(f"attempted to blacklist {target_id} but it is not a valid channel ID")
        respond("Troutpheus can't confirm you're a channel manager! Try adding Troutpheus to this channel, and rerun the command again.")
        exit()
    
    member_ids = set(members_response["members"])

    

    is_cm = False
    if body["user_id"] not in member_ids:
        is_cm = False
    else:
        user = client.users_info(user=body["user_id"])["user"]
        is_cm = user.get("is_admin") or user.get("is_owner")

    if is_cm or body["user_id"] == os.getenv("ADMIN_ID"):
        try:
            BlacklistedChannel.create(channel=target_id)
        except IntegrityError:
            sentry_sdk.logger.info(f"already blacklisted {target_id}")
            respond(f":trouted: *Whack!* It looks like you already blacklisted <#{target_id}> from getting Troutpheus notifications. To whitelist this channel, run `/trout-whitelist <#{target_id}>` in your channel.")
            exit()
        sentry_sdk.logger.info(f"blacklisting {target_id}")
        respond(f":red-x: You've successfully *blacklisted* <#{target_id}> from getting Troutpheus notifications. When members use Troutpheus commands here, they'll be sent as 'only visible to you' messages.\nTo whitelist this channel, run `/trout-whitelist <#{target_id}>` in your channel.")
    else:
        sentry_sdk.logger.info(f"no permissions to blacklist the channel")
        respond(f":trouted: *Whack!* You aren't the channel manager of <#{target_id}>, so you cannot blacklist Troutpheus from this channel. Ask a channel manager to blacklist the channel for you.")
        exit()

@app.command("/trout-whitelist")
def respond_whitelist(ack, respond, body, client, command):
    ack()
    sentry_sdk.logger.info(f"responding to trout whitelist from {body["user_id"]}")

    split_command = command["text"].split(" ")
    if not re.match(channel_id_pat, split_command[0]):
        sentry_sdk.logger.info(f"attempted to blacklist {body["channel_id"]} but it is not valid")
        respond(":trouted: *Whack!* The channel you tried to blacklist isn't valid. The correct syntax is `/trout-blacklist #[CHANNEL NAME]`.")
        exit()
    target_id = split_command[0][2:]
    try:
        target_id = target_id[:target_id.index("|")]
    except ValueError:
         target_id = target_id[:target_id.index(">")]
        
    sentry_sdk.logger.info(f"identified the blacklist req for {target_id}")
    
    try:
        members_response = client.conversations_members(channel=target_id)
    except SlackApiError:
        sentry_sdk.logger.info(f"attempted to whitelist {target_id} but it is not a valid channel ID")
        respond("Troutpheus can't confirm you're a channel manager! Try adding Troutpheus to this channel, and rerun the command again.")
        exit()
    
    member_ids = set(members_response["members"])

    is_cm = False
    if body["user_id"] not in member_ids:
        is_cm = False
    else:
        user = client.users_info(user=body["user_id"])["user"]
        is_cm = user.get("is_admin") or user.get("is_owner")

    if is_cm or body["user_id"] == os.getenv("ADMIN_ID"):
        try:
            channel = BlacklistedChannel.get(channel=target_id)
            channel.delete_instance()
        except BlacklistedChannel.DoesNotExist:
            sentry_sdk.logger.info(f"not blacklisted {target_id}")
            respond(f":trouted: *Whack!* It looks like this channel has not been blacklisted, so I can't whitelist it. Did you mean to blacklist this channel? `/trout-blacklist <#{target_id}>`")
            exit()
        sentry_sdk.logger.info(f"whitelisting {target_id}")
        respond(f":white_check_mark: You've successfully *whitelisted* <#{target_id}> from getting Troutpheus notifications. When members use Troutpheus commands here, her messages will be posted here as well.\nTo blacklist this channel, run `/trout-blacklist <#{target_id}>` in your channel.")
    else:
        sentry_sdk.logger.info(f"no permissions to whitelist the channel")
        respond(f":trouted: *Whack!* You aren't the channel manager of <#{target_id}>, so you cannot whitelist Troutpheus from this channel. Ask a channel manager to whitelist the channel for you.")
        exit()

@app.action("unsub_button")
def unsub(ack, body, say):
    ack()
    sentry_sdk.logger.info(f"responding to unsub req from {body["user"]["id"]}")
    sentry_sdk.metrics.count(
        "unsub",
        1,
        attributes={
            "actor": body["user"]["id"],
        },
    )
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
    sentry_sdk.logger.info(f"responding to resub req from {body["user"]["id"]}")
    sentry_sdk.metrics.count(
        "resub",
        1,
        attributes={
            "actor": body["user"]["id"],
        },
    )
    target_id=body["user"]["id"]
    user = User.get(user_id=target_id)
    user.unsubscribed = False
    user.save()
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
# Start your app
if __name__ == "__main__":
    SocketModeHandler(app, os.getenv("SLACK_API_TOKEN")).start()