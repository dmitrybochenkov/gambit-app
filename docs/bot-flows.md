# Bot Flows

## Registration

### Entry

Bot sends greeting:

> Welcome to Gambit poker club. The bot helps you become a community member. To know how to address you and track achievements, enter your full name, nickname, or both.

The bot must warn that offensive language is not allowed and recommend using the nickname previously used in the club.

### Identifier Choice

Inline keyboard:

- Full name
- Nickname
- Full name + nickname

### Data Entry

Depending on choice, bot asks for data step by step:

- Last name and first name
- Nickname
- Last name and first name, then nickname

### Validation

Bot checks:

- Required fields are present.
- Full name is unique when provided.
- Nickname is unique when provided.
- Text does not contain banned words or obviously invalid input.

If duplicate:

- "This nickname already exists. Try another nickname."
- "This full name already exists. Try another full name."

### Confirmation

Bot sends entered data back to the user for confirmation.

Inline keyboard:

- Confirm
- Enter again

### Admin Review

After confirmation, registration receives status `pending_review`.

Admin manually checks the submitted data. Admin decision:

- Approve: user becomes active member.
- Reject: user is notified and can retry.

### Result

Approved message:

> Full Name (NICKNAME), you have successfully registered.

Rejected message:

> You are not registered. Try another nickname or name.

After approval, bot shows main keyboard.

## Main Keyboard

Reply keyboard:

- Tournament schedule
- Register
- Cancel registration
- Rating
- Your profile
- How to find us

## Tournament Schedule

Bot sends schedule text. MVP can be plain formatted text grouped by date.

Recommended fields:

- Date
- Start time
- Tournament title
- Buy-in or participation conditions, if applicable
- Current registration count, if useful

## Register For Tournament

Bot sends:

> Choose tournament dates you want to register for and tap Confirm.

Inline keyboard:

- Tournament dates for the current week
- Confirm
- Cancel

Behavior:

- User can select one or multiple tournaments.
- Already registered tournaments should be visually marked or disabled.
- Confirmation creates tournament registrations.

## Cancel Tournament Registration

Bot sends:

> Choose tournaments you cannot attend.

Inline keyboard:

- User's active tournament registrations
- Confirm cancellation
- Cancel

Behavior:

- User can select one or multiple tournaments.
- Confirmation cancels selected registrations.

## Rating

Bot asks:

> Which rating do you want to view?

Inline keyboard:

- Current season
- All time
- Knockouts
- Knockouts by period

Recommended output fields:

- Position
- Player display name
- Rating points
- Knockouts, if relevant
- Tournament count, if relevant

## Profile

Bot asks:

> Which period do you want to view?

Inline keyboard:

- Current season
- All time

Profile output:

- Rating
- Knockout count
- Tournament count
- Prize places count
- 1st place count
- 2nd place count
- 3rd place count
- 4th place count
- 5th place count

## How To Find Us

Bot sends address and optional map link.

