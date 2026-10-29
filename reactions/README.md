# Publishing Matchday Reactions

Reactions is personal editorial, separate from automated Research and recaps.
The public tab lives immediately under Home (on phones, open More), and at
https://matchdayterminal.com/?view=reactions. Mondays are the planned cadence;
posts are published deliberately, with no automatic writing or scheduling.

You can send your weekly writing to Codex and ask to publish it as a Reaction.
Include a title and the publication date. Codex can import and deploy it for you.

To import a file yourself, save the reaction as UTF-8 plain text (.txt), with a
blank line between paragraphs, then run from the repository:

    python build_reactions.py --import-text "C:/path/to/reaction.txt" --title "Your title" --date 2026-11-02

This saves a draft in reactions/source. Review that JSON file, then change its
status from "draft" to "published" when ready and run:

    python build_reactions.py

Alternatively add --publish to the import command when the writing is final.
Optional --author and --summary set the byline and card excerpt. Dates are labels,
not a scheduler: publish on Monday rather than marking a future entry published.
The body is a list of plain-text paragraphs; HTML is displayed safely as text.
To revise an entry, edit its source JSON and rebuild. Titles and dates are required.

Commit the source, generated reactions-data.js and reactions/*.html with a new
release note and regenerated updates.js. Follow the repository production workflow
to merge and push main. Deployment rebuilds the public feed and article pages from
published source entries only. Drafts and authoring instructions are not copied to
the public site. Every card opens a permanent /reactions/<slug>.html article URL.

No personal reactions have been invented as sample content. Until the first
publication, visitors see the first-edition message.
