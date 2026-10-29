# RetroDB design mockups

These are picture-only design ideas. They are not part of the app and change nothing in it.

## How to open them

Open any `.html` file in a web browser. In the file manager you can double-click it, or drag it onto a browser window. Each file works on its own, with no internet connection.

Every page also works at phone width. To check, make the browser window narrow.

The facts in every mockup are sample data. They are there to show the layout and have not been checked. Drawings stand in for box art, hardware photos and screenshots.

In the museum mockups, a dashed orange "New" label marks information RetroDB does not store today, such as units sold or launch price.

Text is a little brighter and larger than in the app today, for easier reading.

## Game series progression

These show how a game series changed from one game to the next. The sample series is Tomb Raider, 1996 to 2003.

**`series-timeline/1-timeline-rail.html`: the timeline rail.** The games sit in a row along a timeline that you scroll sideways. Each card lists what was added, changed or removed since the game before, plus the consoles and regions it came out on. Pick a card to see full details below, including a table of how each version looks. Good at: a quick feel for the whole series, and it fits a phone well, one card per screen. Weak at: comparing two games far apart; you have to scroll between them.

**`series-timeline/2-family-tree.html`: the family tree.** Main games run down a trunk, with each port and regional version branching off. Pick any two versions to see them in one picture, with a slider that moves the dividing line between them. Good at: showing graphical differences between versions, which is the clearest way to see them. Weak at: describing what changed in gameplay or story; it needs real screenshots for every version to be worth having.

**`series-timeline/3-comparison-matrix.html`: the comparison table.** Games are columns and topics are rows: platforms, graphics, moves, tools, story, saving and regions. A green edge marks each cell that changed from the game before. A timeline strip on top jumps to any game's column. Good at: following one topic through the whole series, and spotting what changed at a glance. Weak at: phones, where the table has to scroll sideways; it also needs every topic filled in for every game.

## Console museum

Each museum mockup has two views: the browse page and one console's own page. Switch between them with the "Preview" buttons at the top. All three keep what the museum shows today: history, specifications, top 10 games, controllers, search, the type filter and the "write all histories" button.

**`museum/1-generation-hall.html`: the generation hall.** A chart shows how long each console was on sale, so you can see which machines competed. Below it, one hall per generation, with a bar to jump between them. Each console card shows how many of your games it has. The console page adds a "life of the console" timeline, a models tab, an "in my library" tab, and links to the consoles that came before and after. It also has a text-size control. Good at: history and context; it is closest to today's museum, so it is the smallest change. Weak at: needs two new facts per console (the year it stopped being made, and units sold) before the chart works.

**`museum/2-exhibit-plaques.html`: the exhibit gallery.** It looks like a real museum. One console stands in a spotlight at the top, and a different one is chosen each visit. Below, the systems hang in galleries (home consoles, handhelds, computers, arcade), each with a printed plaque in dark text on a light card. The console page has a display case for controllers, "did you know" facts and a shelf of the top 10 games. A button reads the plaque aloud. Good at: easy reading, with high-contrast plaques, larger-text and read-aloud buttons. It also invites browsing. Weak at: it shows the least at once, so finding one console means searching or scrolling a gallery.

**`museum/3-encyclopedia.html`: the encyclopedia.** The browse page lists each maker's family line, such as NES to Super Nintendo to Nintendo 64 to GameCube, plus an A to Z index. Tick up to three consoles and compare their speed, memory, sales and age as bars. The console page reads like an encyclopedia article. It has a fact box, a comparison with the console's main rival, and a section on how the console differed between regions. Good at: facts, comparisons and long reading. Weak at: needs the most new data (processor speed and memory as numbers, family line, rival); the long article suits a large screen better than a phone.
