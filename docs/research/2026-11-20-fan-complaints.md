# What fans complain about in sports analysis (2026-11-20)

**Status:** research only, nothing on the site changed.
**Question:** what do fans complain about when it comes to sports analysis and prediction sites, and what does that mean for Matchday?
**Follows:** `2026-11-16-competitive-analysis.md` (what competitors offer). This note covers the other side: what the audience dislikes.

## Method
Web searches on 2026-11-20 across six themes: rating and ranking backlash, paywalls, win-probability graphics, pick sellers and track records, app clutter and phone tables, and fan surveys on data and personalisation. Results were read as search summaries; individual threads were not opened.

## Sources and how much to trust them
| Kind | Examples | Weight |
|---|---|---|
| Weekly "fans in disbelief" roundups of ESPN FPI | SI FanNation (weeks 4 to 11, 2025), Pro Football Network, The Spun | Shows what makes fans angry. These outlets publish the same headline every week, so they show what gets clicks, not how many fans feel it. |
| Coach and pundit criticism | Rhett Lashlee ("rigged"), Doug Gottlieb on KenPom, Danny Kanell, Bret Bielema vs Josh Pate | Loud, specific, partisan |
| Opinion columns | Defector, The Outline, Awful Announcing, Deadspin | Well-argued, few in number |
| Investigations | Deadspin on Pregame (pick seller) | Strong evidence for that one company |
| Fan surveys | WSC Sports (1,050 US fans, Oct 2025), YouGov, Harris Poll (2,026, Oct 2025), IBM (20,864, Jun 2025), Capgemini (12,017, Mar to Apr 2025) | Large samples, but paid for by companies in the industry, with different questions |
| User reviews | Trustpilot and app-store aggregators on the ESPN app | Self-selected unhappy users |

No Reddit threads were read directly (one 2021 r/CFBAnalysis thread came up through a mirror). None of this is a measurement of Matchday's own visitors.

## Findings: what fans complain about

### 1. "This ranking makes no sense"
The most common complaint by far. Example: after week 9 of 2025, FPI ranked a 3-4 team four places above an 8-0 Power Four team, and fans mocked it. The same "fans in disbelief" piece ran after nearly every week of 2025. One fan's version: advanced stats let "losses not hurt you". Josh Pate's defence, "power ratings are not rankings", is correct, but most readers never see that distinction.
- **Root cause:** a power rating answers "how good is this team?" while fans read it as "who deserves to be ranked?" The site shows the number but not which question it answers, or why the team sits there.

### 2. Accusations of bias and a black box
Fans see an SEC bias in FPI, a coach called the rankings "rigged", and a message-board thread is titled "Bart Torvik hates Kentucky". Critics call the numbers "a black box" that is hard to question. Bracketology gets the same treatment: when Joe Lunardi asked the committee for transparency, fans pointed out that his own process is private.
- **Root cause:** without the method and the inputs, any surprising number gets read as an agenda.

### 3. Preseason assumptions linger, and newcomers get noticed late
Fans complain that models are "slow to the party" with teams that weren't expected to be good. A related complaint is that ratings change week to week instead of committing to one prediction. The one systematic check found, a New York Times analysis of playoff-era seasons, did not support the idea that preseason polls hold teams back. So the complaint is about how it feels as much as about the facts.
- **Matchday's own evidence:** its football record is weakest in September (see `model-vs-market-status` and the 2026-11-11 notes). It has the same problem the fans describe.

### 4. Paywalls
SP+ moved behind ESPN+, and a 2021 r/CFBAnalysis thread asked for a free alternative. KenPom's detailed pages are paid ($24.95 a year according to SI). ESPN moved written analysis behind a paywall in 2020. Fans pay for KenPom, so the complaint is about losing free access, not about the price.

### 5. Nobody keeps score of the forecasters
A Deadspin investigation of Pregame found its picks lost almost $310,000 between 2011 and May 2016, even by the company's own generous records. Guides for spotting picks scams all say the same thing: never trust anyone without a complete, dated, public record. Among mainstream models, Cade Massey said of one of his ratings' records, "we haven't tracked [it]". Squawka's model is the one example found that grades every call on its public page as of kickoff and never edits it.

### 6. Win probability as "gambling brain" and math replacing fun
Defector argued that ESPN's live win-probability graphic says nothing the score doesn't and pushes fans toward betting, which matters now that ESPN runs a sportsbook. Bill Simmons asked of a similar graphic, "Who is that for?" The Outline described sports talk turning from fun into math. In YouGov's survey, 54% say real-time stats improve watching a game, but only 21% care about win probability specifically.

### 7. Overload, clutter and things that aren't relevant to me
In WSC Sports' survey, 53% of Millennials and 43% of Gen X often feel overwhelmed by the amount of sports content, and more than half have cancelled or switched a service because the content didn't feel relevant. IBM's survey ranks faster recaps (67%) and personalisation (65%) as the most wanted improvements. ESPN app reviews complain about ads, clutter and navigation. Harris found that fans like control over *how things are shown*, such as which stats appear, but not over outcomes.

### 8. Tables on a phone
Common complaints: names scroll away from the numbers, tables that scroll separately fall out of line, and sites tell phone users to rotate the screen (Torvik, per the 11-16 note). Baseball-Reference fixed it by freezing the name column while the numbers scroll.

### Little evidence found
- Complaints about jargon specifically. Glossaries exist (Baseball-Reference's "?"), but no strong complaint record turned up.
- Any demand for cosmetic customisation such as themes or skins. The personalisation fans ask for is about relevance (my team, my games) and what is shown, not looks.

## What this means for Matchday

### Where it is already on the right side
| Complaint | Matchday today |
|---|---|
| Paywalls (4) | Free, no account, no ads |
| No public record (5) | Picks locked before kickoff and graded in public, with calibration and a split by agreement with the market. This is rarer than anything else on the list. |
| Gambling framing (6) | Positioned as fan research; the CLV work is framed as a forecasting test, not betting |
| Phone tables (8) | Builds 0925P to 0925V reworked tables for phones. The 11-11 review found phone Rankings hiding every number, so check that this is fixed. |

### Where it has the same problems as everyone else
| Complaint | Gap |
|---|---|
| Makes no sense (1) | The rating is shown without saying which question it answers or why the team is there |
| Black box (2) | The engine is private and there is no method page (11-16 note, "No method on show") |
| Preseason (3) | September is the weakest month, and the site doesn't show how much of a rating is still preseason assumption |
| Overload (7) | Ten tabs, and the 11-11 review found dense pages with very small text. "My teams" exists but only reorders lists. |

### Opportunities, in order of evidence
1. **One sentence of "why" next to every rating and every change.** For example: "Up 2.1: beat Texas by 14 when the model expected a 3-point loss." Put a résumé figure (record, strength of record) next to the power rating and label the rating "how good, not how deserving", so a 3-4 team above an 8-0 team reads as intended rather than as a bug. This answers complaint 1 directly and builds on the 11-16 recommendation that game pages say why.
2. **Show how much preseason is left.** Something like "62% results, 38% preseason expectation", falling over the season. It answers complaints 2 and 3 honestly, including Matchday's own September problem. It needs the engine to expose the prior weight; check TRDLab before promising it.
3. **Make the record the headline.** Fans' strongest trust signal is a complete, dated, uneditable record, and Matchday already has one. Ideas: a weekly "what we got wrong" section on Home on Sundays, the downloadable CSV, and third-party tracking (from the 11-16 note).
4. **A relevance mode, not more data.** "Your team this week": its game, the two or three other games that affect it, and one line on what changed. This addresses the overload complaint with the least new interface, and it is the earlier "rooting guide" idea with evidence behind it.
5. **A method page in plain words.** What goes in (results, margin, opponent, preseason inputs), what doesn't (other sites' power ratings, per `own-ratings-only`), and how the record is kept. It answers complaint 2 without publishing the engine.

### What the evidence argues against
- Live in-game win-probability graphics (6). They're also blocked by the data sources available.
- Cosmetic customisation as the way to make the site fun: no demand found.
- Anything that adds tabs or panels before the overload in point 7 is reduced.

## Caveats
- Most evidence is media roundups and opinion pieces, which pick the loudest reactions. The surveys are larger but paid for by the industry, and none is about college sports specifically.
- Several sources are from earlier seasons (2016 to 2021 for paywalls and columns). The FPI backlash is from the 2025 season.
- Nothing here measures Matchday's own visitors. No analytics source was checked.
