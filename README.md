# Job Finder

A simple local tool that finds the latest job openings in any country for the roles you care about.

## Start it
Double-click **`Start Job Finder.bat`**. A browser tab opens at http://localhost:8765. Keep the black window open while you search.

## Stop it
Use any of these:
- Click **⏻ Stop Job Finder** at the top right of the page.
- Double-click **`Stop Job Finder.bat`**.
- Close the black Job Finder window, or press Ctrl+C in it.

## Use it
1. Type a **country** (optionally a city).
2. Pick **how recent** the jobs should be, **how deep** to search, and the **job type** (any, part-time only or full-time only).
3. Tick the **job types** you want, and add any extra phrases.
4. Under **Where to search**, untick any sources you don't want.
5. Press **Search jobs**.

Then you can:
- Use the sections at the top of the results:
  - **🎓 No experience needed:** the ad says no experience is required ("freshers welcome", "no prior experience", "Quereinstieg", 0 years), or it's an internship, trainee or volunteer role.
  - **🌱 Entry level (0–1 yr):** the above, plus jobs asking for up to 1 year of experience or labelled entry level, junior or graduate.
  - **⏱ Part-time:** jobs whose ad or listing says part-time, or 30 hours a week or fewer.

  Many ads don't mention experience at all, so these sections show only jobs whose ad says so. Each job also gets tags for its job type and how much experience it asks for.
- Filter by category, source or a keyword, and sort the results.
- Filter by **language**. After a search, the tool reads each job ad to see which languages it needs: the language the ad is written in, plus any it asks for, such as "fluent in Arabic" or "Deutschkenntnisse". It also notes languages an ad calls "a plus". Tick the languages you speak, then choose *Hide jobs that need a language I don't speak* or *Only jobs that need a language I picked*. On each job, languages you haven't ticked show in red.
- Mark each job as **Save**, **Mark applied**, or **Not for me**.
- See a **NEW** tag on jobs that weren't there last time.
- Use **Download CSV** to get a spreadsheet of the results.
- Use the **Also check these sites** links (Indeed, Glassdoor, ReliefWeb, UNjobs, Naukri, NHS Jobs and others) for sites that can't be searched automatically.

## My saved jobs
The **★ My saved jobs** section shows every job you've saved, applied to or marked "Not for me", even before you search.
- **Saved** and **Applied** tabs show each job's link, company, the date you saved or applied, and its job type and experience tags.
- Each job has a **notes** box for deadlines, contacts or interview dates. Notes are saved when you click away from the box.
- **Not for me** lets you undo a dismissal.
- **Download CSV** exports your saved and applied jobs, with notes.

All of this is stored in **`my_jobs.json`** in this folder. It stays after you close the tool, restart your computer or clear your browser. To back up your saved jobs, copy this file. Don't delete it unless you want to start over.

## Change what gets searched
Edit `categories.json`, which holds the job categories and their search phrases, then restart the tool.

The German job agency only understands German. `categories.json` therefore also has a `german_keywords` list with a German version of each phrase. If you add a new English phrase and want it searched in Germany, add its German version there too.

## Sources
All free, with no sign-up needed:

| Source | Countries | Good for |
|---|---|---|
| LinkedIn | Any | The most jobs overall |
| Workable | Any | Jobs posted directly by companies and schools |
| Impactpool | Any | NGO, UN and development jobs, such as psychosocial support (MHPSS) roles. Ads don't show a post date, so these appear at the end when sorting by newest. |
| NHS Jobs | UK only | Psychology, wellbeing and mental health jobs in the NHS |
| Bundesagentur für Arbeit | Germany only | Germany's official job board, searched in German |
| Remotive and Jobicy | Remote | Remote jobs open to your country |

What the tool reads from each job ad (languages, job type and experience) is saved in `details_cache.json`, so jobs you've already seen are checked instantly. You can safely delete this file.

**Part-time only searches:** LinkedIn's own part-time filter isn't reliable; in testing, most of its "part-time" results were full-time. The tool therefore checks each ad's stated employment type and hides the ones that aren't part-time. The note above the results says how many were hidden.

If you see "LinkedIn is limiting requests", wait a few minutes or use Quick mode.
