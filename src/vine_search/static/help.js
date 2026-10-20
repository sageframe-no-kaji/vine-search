"use strict";
window.VINE_HELP_TOPICS = Object.freeze([
  {
    id: "start",
    title: "Getting started",
    html: `<p>VineSearch keeps a local history of products your account has seen, ranks them with your tracker rules, and keeps local review progress separate from Amazon’s status.</p>
      <ol><li><a href="#help?topic=connection">Connect Amazon</a> through the installation’s private browser.</li><li>Use <a href="#help?topic=discover">Discover</a> to search Amazon now or browse saved observations.</li><li><a href="#help?topic=trackers">Create a tracker</a> to identify matches. Add scheduled searches and notifications when you want them.</li></ol>
      <p>Live search checks the Additional Items pages Amazon exposes for your query. Saved history is limited to what this installation actually captured. A completed search does not establish coverage of the entire Vine catalog.</p>
      <p><a href="#help?topic=reviews">Reviews</a> combines observed Amazon status with your own progress labels. <a href="#help?topic=visibility">Hide and restore</a> helps you keep either list manageable without deleting its records.</p>`,
  },
  {
    id: "trackers",
    title: "Set up a tracker",
    html: `<p>A tracker applies rules to collected product titles. Its name is a label; its Amazon query finds candidates; its include phrases decide which saved titles match. These are separate fields.</p>
      <ol><li><strong>Name:</strong> choose a useful label, such as Network Rack.</li><li><strong>Amazon search query:</strong> enter a query such as <code>network rack</code> if you want scheduled searches. A blank query is fine for matching existing history.</li><li><strong>Include phrases:</strong> enter one literal phrase per line. Choose Any phrase for alternatives or All phrases when every phrase must occur in the title.</li><li><strong>Excluded phrases:</strong> enter unwanted phrases, such as <code>wine rack</code> and <code>shoe rack</code>. Any exclusion overrides a positive match.</li><li><strong>Observed categories:</strong> normally leave this blank. A restriction requires an exact observed category; products with unknown categories will not match.</li><li>Set a minimum point score, then enable the tracker. Add a schedule or alerts only if needed, and click Save tracker.</li></ol>
      <p>Blank include phrases let all titles through that part of the rule. Exclusions, categories, freshness and the minimum score still apply. A tracker’s rules can match products from any collected source, not only results from its own query.</p>
      <p>Only products observed within the freshness window qualify; the initial value is 168 hours (7 days). Open Ranking weights and freshness to change it. <a href="#help?topic=ranking">How scoring and freshness work</a>.</p>
      <p>Saving or editing a tracker does not send alerts for existing inventory. <a href="#help?topic=notifications">How new-match alerts work</a>. If saving fails, the form keeps your values and identifies the field to correct; <a href="#help?topic=troubleshooting">see save troubleshooting</a>.</p>`,
  },
  {
    id: "matching",
    title: "Phrase matching and a 10-inch rack",
    html: `<p>Matching looks for literal, contiguous text inside a title and ignores letter case. It does not understand product type, dimensions, synonyms or compatibility. The phrase <code>rack</code> matches <code>wine rack</code> because those letters occur in that title.</p>
      <p>For a 10-inch rack, start with Amazon query <code>10 inch network rack</code>. Set Any phrase and use specific alternatives in Include phrases:</p>
      <pre><code>10 inch rack
10-inch rack
10&quot; rack</code></pre>
      <p>Use exclusions such as <code>wine rack</code> and <code>shoe rack</code>. Leave categories blank unless the listings have a reliable observed category. This example is a rule to inspect and adapt; it does not establish that a product fits your equipment.</p>
      <p><code>10 inch server rack</code> does not contain the contiguous phrase <code>10 inch rack</code>. Add <code>10 inch server rack</code> as another Any alternative when that is the wording you want. Bare alternatives <code>10 inch</code>, <code>10-inch</code> and <code>10&quot;</code> also match unrelated products of that size across collected history.</p>
      <p>Alternatively, choose All phrases with these two lines:</p>
      <pre><code>rack
10 inch</code></pre>
      <p>Both must occur somewhere in the title, so intervening words are allowed. That rule still will not match <code>10-inch</code>; use a separate tracker for another punctuation form. All phrases with every spelling would require every spelling in the same title. The current rules do not support grouped conditions such as “rack AND any of these three size spellings.”</p>
      <p><a href="#help?topic=ranking">Scores rank the titles that pass these rules</a>; they do not measure dimensional fit.</p>`,
  },
  {
    id: "ranking",
    title: "Scores, weights and freshness",
    html: `<p>A score is a sum of points from your rules, not a percentage, probability or confidence estimate. Each matching include phrase contributes its phrase weight. A product can match more than one phrase, so its score can exceed 100.</p>
      <table><thead><tr><th>Setting</th><th>What it does</th></tr></thead><tbody>
      <tr><td>Per matching phrase</td><td>Adds this many points for each matching include phrase.</td></tr>
      <tr><td>Category match</td><td>Adds points when a configured category restriction matches the product’s observed category. No category restriction means no category points.</td></tr>
      <tr><td>Freshness bonus</td><td>Adds the full weight when just observed, then decreases linearly to zero at the end of the freshness window.</td></tr>
      <tr><td>Only match items seen within</td><td>Excludes older observations entirely. This is a filter as well as the window used for the bonus.</td></tr>
      <tr><td>Minimum match score</td><td>The point total required to count as a match after the other rules pass.</td></tr></tbody></table>
      <p>Example: phrase weight 30, freshness weight 10, freshness window 168 hours. One matching phrase on a product last observed 84 hours ago earns 30 + 5 = 35 points. Two matching phrases earn 65. A category bonus adds points only when you configured and matched a category restriction.</p>
      <p>Exclusions always remove a match. A missing required phrase, an unmatched or unknown required category, an observation older than the freshness window, or a score below the minimum also prevents a match. Product cards explain their score contributions.</p>
      <p>Weights and minimum score accept whole numbers from 0 to 1000; the freshness window accepts 1 to 8760 hours. <a href="#help?topic=matching">Phrase matching examples</a>.</p>`,
  },
  {
    id: "schedules",
    title: "Schedules and search limits",
    html: `<p>A tracker searches Amazon automatically only when the tracker is enabled, Search Amazon on a schedule is checked, its Amazon query is nonempty, and scheduled collection is enabled in Settings. Its interval accepts 5 to 10080 minutes. Saved settings apply to newly queued work.</p>
      <p>Every search, whether started manually or by a tracker schedule, checks all result pages Amazon exposes for its query. Searches have no page cap or total time limit. There is no search-page setting to configure.</p>
      <p>Recommended for You and Available for All queue collection retain a page limit, and queue collection and review sync have a time limit in Settings. These limits do not apply to searches. Activity identifies the stopping reason and how many items and completed pages were saved. Older runs may lack the exact stopping reason.</p>
      <p>Individual page loads still have a timeout for both manual and scheduled searches. Sign-in, a page error, repeated pagination or your Cancel request can stop it; the status distinguishes an incomplete run from a complete one.</p>
      <p>All collection, review sync, product-details requests and login use the same dedicated browser, one at a time. A queued request waits for that browser. Pausing scheduled collection does not cancel an already running request; use its Cancel control when needed.</p>
      <p>Recommended for You and Available for All use the queue settings. Review sync has its own page limit, shared between Awaiting Review and Reviewed, plus the background time limit. <a href="#settings">Open Settings</a>.</p>`,
  },
  {
    id: "notifications",
    title: "Notifications and review reminders",
    html: `<p>Product alerts need all of these: an enabled tracker whose rules match the product, Alert on new eligible matches enabled on that tracker, Notifications enabled in Settings, and a saved destination. The tracker’s alert checkbox alone does not configure delivery.</p>
      <ol><li>In Settings, choose webhook JSON or ntfy and enter the destination. Add the optional bearer token if your service needs it.</li><li>Save Settings, then use Send test to saved destination. The test bypasses notification enablement and quiet hours.</li><li>Check Activity for the delivery result. Enable ordinary notifications and the relevant tracker’s alerts when ready.</li></ol>
      <p>The first complete or page/time-limited capture of a scope creates a quiet baseline. Existing inventory is not replayed when you enable alerts or edit tracker rules. Subsequent eligible additions can alert; an already seen product stays suppressed for that tracker across collected sources.</p>
      <p>Immediate delivery sends eligible alerts individually. Digest delivery groups pending alerts at the chosen interval. Quiet hours use the saved timezone; matching start and end times disable quiet hours. Delivery failures retry with backoff, up to five attempts. A crash around delivery can cause a repeat, so external receipt is not guaranteed to be exactly once.</p>
      <p>Alert again when a product returns is off by default. A return requires a prior complete, comparable scan to have established absence in the same scope. Incomplete scans never establish disappearance.</p>
      <p>Hiding a product does not mute its tracker notifications. Change the tracker’s alert setting or matching rules to stop those alerts. Hidden review records also remain eligible for review reminders, which follow the underlying obligation and local progress.</p>
      <p>Review reminders require the reminder switch and your notification destination settings. Personal review targets are your own dates, not a statement of Amazon’s requirements. <a href="#help?topic=reviews">Review progress</a>.</p>`,
  },
  {
    id: "discover",
    title: "Discover and product details",
    html: `<p>Refresh queues refreshes the enabled Recommended for You and Available for All queues; it does not run your typed query. Search uses the selected search tab.</p><p>Collected history searches titles already observed by this installation. Live Amazon search asks Amazon for the Additional Items pages matching your query. Amazon may return relevant results whose titles do not repeat the query text.</p>
      <p>Live results belong to the selected search and use a fixed Additional Items source. The count separates how many items the run collected from how many match your current tracker, score, freshness and visibility filters. If there are no matches, Clear filters shows all items collected by that run, including hidden items.</p>
      <p>Observed in filters apply to history. For you means Recommended for You; Available for all is that queue; Additional items represents captured search results. Product cards can have several sources, but repeating a search does not create another card for the same Amazon product.</p>
      <p>Every product VineSearch encounters during a search or queue refresh is saved automatically, including products that match no tracker. You do not need a separate save action. Browsing Amazon in your everyday Safari window is outside this collector and does not add observations to VineSearch.</p><p><strong>Open product</strong> opens that product’s Amazon page. <strong>See details</strong> asks the dedicated browser to find the exact captured item and read its Vine details. It can show an observed Estimated Taxable Value, description and variations. It does not request or order an item, and it does not change variations.</p>
      <p>Details can wait behind another browser request. You may close the window and reopen the saved result from Activity. Missing ETV is shown as Unavailable, never as zero. A product that has disappeared from its captured page may need a new collection before details are available.</p>
      <p>Observations and ETV have timestamps and can change. Only the pages actually checked are represented; current availability is determined on Amazon. <a href="#help?topic=visibility">Hide or restore unwanted products</a>.</p>`,
  },
  {
    id: "connection",
    title: "Connect or reconnect Amazon",
    html: `<ol><li>Choose Connect Amazon, then Open login browser.</li><li>Wait until the private browser is ready. If a collection is running, login waits for the same browser.</li><li>Use Open full-size login browser for more room, especially on a phone. Sign in directly on Amazon and complete any verification Amazon requests.</li><li>Return to VineSearch and wait for Amazon connected. Keep the login session open until Vine access is verified.</li></ol>
      <p>The embedded browser and full-size tab show the same login session. Closing the panel does not submit credentials or complete login. Cancel login ends the temporary login session; an expired or failed session can be started again.</p>
      <p>Your Amazon session stays in the collector’s private storage. The web application does not store your password in a dashboard field. Disconnect preserves the saved session; Disconnect and forget session removes it and requires signing in again.</p>
      <p>Saved history stays available when Amazon is disconnected. If Amazon requests sign-in or a challenge during a collection, the run records that state and keeps the observations it captured. Reconnect, then run the work again.</p>`,
  },
  {
    id: "reviews",
    title: "Reviews, imports and local progress",
    html: `<p>Sync reviews reads Amazon’s Awaiting Review and Reviewed pages. Amazon observed status is what those pages reported at the last observation. Local progress is your own Not started, In progress or Marked submitted label; changing it does not submit a review or change Amazon’s status.</p>
      <p>Product thumbnails use the same image setting as Discover. Filters can select observed status, local progress, source or title. Summary progress counts describe the displayed page, not your account’s official review percentage.</p>
      <p>Review sync is bounded by its saved page limit and the background time limit. Pages alternate between Awaiting Review and Reviewed when the page and time limits permit. A one-page limit can capture only the first section. A partial sync preserves earlier statuses and never marks a missing record completed.</p>
      <p>Import / export accepts a JSON list of review metadata. Choose a file, inspect the accepted, duplicate and rejected records, then explicitly import the accepted metadata. Identity, variant, dates, statuses, links and optional rating are kept. Review bodies, drafts, notes, uploaded photos and credentials are excluded.</p>
      <p>Known identities update their metadata; new identities become separate records. Where Amazon’s order identifier was not captured, identity is provisional and combines the available product, variant and order information. Check ambiguous imports in the preview.</p>
      <p>Observed deadlines and your configured personal targets are labeled separately. Hiding a review does not remove its obligation or stop applicable reminders. <a href="#help?topic=visibility">Visibility controls</a>.</p>`,
  },
  {
    id: "visibility",
    title: "Hide, bulk hide and restore",
    html: `<p>Discover and Reviews start with Visible records. Hide removes an item from that list locally while preserving its identity, observations and progress. Choose Hidden in the visibility menu to find it again, or All records to see both.</p>
      <ol><li>Use Hide on one card or review row for an individual item.</li><li>Check selected items, or use Select displayed for every item on the current page.</li><li>Choose Hide selected. Other pages are not included.</li><li>Choose Hidden, select items and use Restore selected, or use Restore on one item.</li></ol>
      <p>Visibility survives future scans and metadata imports. Product visibility and review visibility are independent: hiding a discovery product does not hide its review record. Hiding does not change anything on Amazon.</p>
      <p>Hidden products still participate in tracker matching and notifications. Hidden reviews can still receive applicable reminders. Use tracker rules and notification settings to change alerts.</p>`,
  },
  {
    id: "settings",
    title: "Settings, privacy and history",
    html: `<p>Collection settings control scheduled queue polling, background page and time limits, and the master pause for scheduled work. Each tracker has its own query and schedule. Every manual and scheduled search checks all available result pages; the page and time limits apply only to queues and review sync. <a href="#help?topic=schedules">Schedules and limits</a>.</p>
      <p>Review settings control sync frequency, its shared page limit, reminders and optional personal targets. Notification settings control the delivery service, destination, optional token, cadence, timezone and quiet hours. Save before testing a destination.</p>
      <p>Image privacy can use the application proxy, load directly from allowlisted Amazon image hosts, or hide images. Proxy mode lets the application fetch and cache the thumbnail. Direct mode contacts the image host from your browser.</p>
      <p>Changing the retention window does not delete anything. Preview cleanup first, then explicitly apply it. Cleanup removes old retained history while preserving minimal alert identities so recollecting an old product does not replay its original alert.</p>
      <p>Export downloads application data for private storage. Metadata exports omit delivery credentials and Amazon session files; a full database backup can contain private settings. Follow the installation’s backup procedure for a restorable database copy.</p>
      <p>Reset settings restores defaults. Delete application data removes product history, review records, jobs and delivery history while preserving tracker definitions and settings. Disconnect and forget session is a separate action. Each destructive action identifies what it changes and requires confirmation.</p>`,
  },
  {
    id: "troubleshooting",
    title: "Saving and other troubleshooting",
    html: `<h3>A tracker did not save</h3><p>Keep the form open and read its error message. Invalid fields are brought into view, including fields inside Ranking weights and freshness. A failed request preserves the values you entered.</p>
      <ul><li>A name must contain text. It labels the tracker; it does not supply the Amazon query.</li><li>A scheduled tracker needs a nonempty Amazon query.</li><li>Weights and minimum score are whole numbers from 0 to 1000.</li><li>Freshness is 1 to 8760 hours; interval is 5 to 10080 minutes. Searches have no page limit.</li><li>A save is confirmed only after the returned tracker ID appears in a fresh saved-list read. The editor stays on that tracker. If the server accepts it but list confirmation fails or omits it, your form stays intact; use Retry list refresh, which checks the known ID without creating another tracker.</li></ul>
      <p>Help links open a separate tab. Drafts also remain in memory when you move to another application view and return. Reloading or closing the tab discards unsaved drafts, so save first. Failed requests preserve your form; a list-refresh failure after acceptance has a separate confirmation message.</p>
      <h3>A search collected items but shows none</h3><p>Check tracker, minimum score, freshness and visibility filters. Live search shows the collected total separately from matching results. Clear filters returns all items from that run. History queue filters do not apply to live search.</p>
      <h3>A job is queued, incomplete or needs login</h3><p>Queued means it is waiting for the shared browser. Activity shows progress and any stopping reason. Page or time limits explain bounded background runs; any search can still stop for a page error, repeated pagination, sign-in or cancellation. Reconnect if requested, then run again.</p>
      <h3>An alert did not arrive</h3><p>Check the tracker’s rules and alert switch, global notification enablement, destination, cadence and quiet hours. Existing inventory is not replayed when alerts are enabled. Save the destination, send a test, then inspect delivery status in Activity.</p>
      <h3>A product photo or ETV is missing</h3><p>Check the image privacy setting and refresh observations. Some captured listings have no usable thumbnail. ETV is shown only when Amazon actually exposed it for the observed selection; missing ETV is Unavailable.</p>`,
  },
]);
