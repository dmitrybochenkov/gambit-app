# Gambit Poker Club Bot

## Goal

Telegram bot for a poker club community. The first version handles member registration, profile/statistics display, tournament schedule, tournament self-registration, cancellation, ratings, and venue information.

Later phases may add a web app and a fuller admin interface.

## Roles

### Player

Club member or candidate member using the Telegram bot.

Main needs:

- Register in the club with real name, nickname, or both.
- See tournament schedule.
- Register for upcoming tournaments.
- Cancel tournament registration.
- View ratings and personal achievements.
- Find club address.

### Admin

Club manager who verifies members, manages tournaments, enters results, and controls statistics.

Main needs:

- Review and approve or reject registrations.
- Prevent duplicates and inappropriate profile data.
- Create and edit tournament schedule.
- View and manage tournament registrations.
- Enter tournament results.
- Maintain ratings and player statistics.

## MVP Scope

### Included

- Telegram bot registration flow.
- Manual admin approval for new members.
- Main bot keyboard after approval.
- Tournament schedule display.
- Tournament self-registration for current week.
- Tournament registration cancellation.
- Ratings views.
- Player profile statistics.
- Club address.
- Basic admin interface or admin bot commands for MVP operations.

### Deferred

- Public web app.
- Payment handling.
- Automatic import from poker software.
- Deep anti-fraud or identity verification.
- Complex CRM functions.

## Open Questions

- What is the source of truth for historical player results?
- How are tournament results entered today?
- How many admins will use the system?
- Should rejected users be allowed to retry immediately?
- Are real names mandatory, optional, or only one of several allowed identifiers?
- Should players see full names of other members in ratings, or only nicknames?
- What are the exact rating formulas?
- What defines the current season?
- Are tournament registrations capacity-limited?
- Is there a registration cutoff time before tournament start?

