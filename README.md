# Troutpheus
A Slack bot that mimics the trout functionality of Wikipedia

Did someone do something absurdly silly or stupid? Whack them with trouts! This bot sends a trout to any hackclubber and publicly enshrines the trout. Try /trout @[USER] [REASON] on the Hack Club Slack to get started.

## Development
Rename `.env.example` to `.env`. Then, replace the values in .env accordingly with your Slack bot tokens, postgres database URL, channel/canvas info, Sentry logging, blacklisting, and rate limits.

Then, run the `app.py` script:

```python3 app.py```

## Deploying
You can run the above as a quick way to deploy the app, or you can build the docker image.

To do this, run the following:

```docker build -t normalperson543/troutpheus .```

Then create and run a container:

```docker run -d normalperson543/troutpheus```

## Username migration
This will go through each user in the database, query the slack api for their real name, and replace the username on the database with their real name. This was used by me to switch from pulling the Slack username to their real name as listed on their profile.

Run the following script in the `libs/username_migration` folder to do this:

```python3 username_migrate.py```