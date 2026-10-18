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
2. Pick **how recent** the jobs should be and **how deep** to search.
3. Tick the **job types** you want, and add any extra phrases.
4. Press **Search jobs**.

Then you can:
- Filter by category or a keyword, and sort the results.
- Filter by **language**. After a search, the tool reads each job ad to see which languages it needs: the language the ad is written in, plus any it asks for, such as "fluent in Arabic" or "Deutschkenntnisse". It also notes languages an ad calls "a plus". Tick the languages you speak, then choose *Hide jobs that need a language I don't speak* or *Only jobs that need a language I picked*. On each job, languages you haven't ticked show in red.
- Mark each job as **Save**, **Mark applied**, or **Not for me**. The tool remembers this between searches.
- See a **NEW** tag on jobs that weren't there last time.
- Use **Download CSV** to get a spreadsheet of the results.
- Use the **Also check these sites** links (Indeed, Glassdoor, ReliefWeb, UNjobs, Naukri, NHS Jobs and others) for sites that can't be searched automatically.

## Change what gets searched
Edit `categories.json`, which holds the job categories and their search phrases, then restart the tool.

## Sources
- LinkedIn public job listings (any country, no login).
- Remotive (remote jobs open to your country or worldwide).

Language results are saved in `language_cache.json`, so jobs you've already seen are checked instantly. You can safely delete this file.

If you see "LinkedIn is limiting requests", wait a few minutes or use Quick mode.
