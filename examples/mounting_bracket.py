"""Parametric mounting bracket with mounting holes."""
from cadgen import build123d as bd
from cadgen import step, stl

# Explicit dimensions in mm
LENGTH = 60.0
WIDTH = 30.0
HEIGHT = 25.0
THICKNESS = 5.0
HOLE_DIA = 5.0


@stl(out="../output/bracket.stl")
@step(out="../output/bracket.step")
def mounting_bracket():
    # Base horizontal plate
    base = bd.Box(LENGTH, WIDTH, THICKNESS)
    # Vertical wall at one end
    wall = bd.Pos(-(LENGTH - THICKNESS) / 2, 0, (HEIGHT - THICKNESS) / 2) * bd.Box(THICKNESS, WIDTH, HEIGHT)
    bracket = base + wall

    # Base mounting hole
    hole_base = bd.Pos(LENGTH / 4, 0, 0) * bd.Cylinder(radius=HOLE_DIA / 2, height=THICKNESS * 2)
    bracket -= hole_base

    # Wall mounting hole
    hole_wall = bd.Pos(-(LENGTH - THICKNESS) / 2, 0, (HEIGHT - THICKNESS) / 2) * (
        bd.Rotation(0, 90, 0) * bd.Cylinder(radius=HOLE_DIA / 2, height=THICKNESS * 2)
    )
    bracket -= hole_wall

    bracket.label = "mounting_bracket"
    return bracket


if __name__ == "__main__":
    mounting_bracket()
