# Admin Concept

## MVP Admin Surface

For the first version, admin features can be implemented either as:

- Admin-only Telegram bot commands and inline keyboards.
- Small protected web admin panel.

Recommended MVP path: start with admin-only Telegram flows for speed, but design the data model so a web admin can be added without rewriting the core.

## Admin Sections

### Registration Review

Admin sees pending registrations.

For each request:

- Telegram username
- Submitted full name
- Submitted nickname
- Duplicate warnings
- Creation time

Actions:

- Approve
- Reject
- Edit submitted data
- Block user

### Players

Player list with search and filters.

Filters:

- Active
- Pending review
- Rejected
- Blocked

Actions:

- View profile
- Edit full name
- Edit nickname
- Block or unblock
- Merge duplicates, later phase

### Tournaments

Tournament calendar and list.

Actions:

- Create tournament
- Edit tournament
- Publish tournament
- Cancel tournament
- View registrations
- Export player list

Fields:

- Title
- Date and time
- Season
- Registration close time
- Capacity
- Description
- Status

### Tournament Registrations

Admin can view players registered for each tournament.

Actions:

- Add player manually
- Cancel player registration
- Mark attendance
- Mark no-show

### Results

Admin enters final results after tournament.

Fields:

- Player
- Place
- Knockouts
- Rating points
- Prize amount, optional

Actions:

- Save draft results
- Publish results
- Recalculate ratings

### Ratings

Admin can view calculated rating tables.

Rating types:

- Current season
- All time
- Knockouts
- Knockouts by period

Admin needs clear visibility into the formula used for each rating.

### Settings

Settings to define before launch:

- Club address
- Active season
- Banned words list
- Rating formula
- Registration cutoff default
- Admin users

## Web Admin Later

Suggested navigation:

- Dashboard
- Registrations
- Players
- Tournaments
- Results
- Ratings
- Settings

Dashboard widgets:

- Pending registrations
- Upcoming tournaments
- Registrations this week
- Recent results
- Top current-season players

