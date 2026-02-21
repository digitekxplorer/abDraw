# abDraw
abDraw is a lightweight desktop drawing application built with Python and Tkinter, designed for creating simple diagrams, flowcharts, and technical sketches.
Features

Drawing tools — line, arrow, rectangle, square, circle, ellipse, triangle, and text
Orthogonal lines — multi-turn 90° lines and arrows built by clicking to place waypoints, with right-click or Enter to finish; flip routing between horizontal-first and vertical-first with R
Shape snapping — line and ortho endpoints snap to connection points on nearby shapes
Grid — toggleable dot or line grid with configurable spacing (10–50 px); snap-to-grid for precise placement
Labels — attach a moveable text label to any shape; line labels default to above the line
Selection & editing — drag to move shapes, drag corner handles to resize, drag endpoint/waypoint handles to re-route lines
Undo / Redo — full history stack (50 levels)
Copy / Paste — duplicate any shape with an automatic offset
Z-order — bring to front / send to back
File format — saves and loads .abdraw files (JSON)
PNG export — renders the canvas including grid to a PNG via Pillow
