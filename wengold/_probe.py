"""A local server behind the IDE page: edit, save, build.

The page was a snapshot — everything embedded at build time, no backend. That made
it safe (a static file cannot damage anything) and useless for editing. This module
adds the backend, and the whole design is about making one narrow capability safe:

    the page may write **only** files that already exist **inside the project root**

That is deliberately stricter than "an editor":

  * **bind to 127.0.0.1 only.** No `0.0.0.0`, no LAN exposure. A file-writing HTTP
