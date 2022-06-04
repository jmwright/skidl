# -*- coding: utf-8 -*-

# The MIT License (MIT) - Copyright (c) 2016-2021 Dave Vandenbout.

"""
Autoplacer for arranging symbols in a schematic.
"""

from __future__ import (  # isort:skip
    absolute_import,
    division,
    print_function,
    unicode_literals,
)

__all__ = [
    "place",
    "PlacementFailure",
]

from builtins import range, zip
from collections import defaultdict
import math
import random

from future import standard_library

from ...logger import active_logger
from ...part import Part
from ...utilities import *
from .common import *
from .geometry import *
from .route import *

standard_library.install_aliases()

###################################################################
#
# OVERVIEW OF AUTOPLACER
#
# The input is a Node containing parts, each with a bounding box.
#
# The positions of each part are set.
#
###################################################################

def draw_force(part, force, scr, tx, font, color=(128,0,0)):
    force *= 200
    anchor = part.bbox.ctr.dot(part.tx)
    draw_seg(Segment(anchor, anchor+force), scr, tx, color=color, thickness=5, dot_radius=5)

def draw_placement(parts, nets, scr, tx, font):
    draw_clear(scr)
    for part in parts:
        draw_part(part, scr, tx, font)
    for net in nets:
        draw_net(net, parts, scr, tx, font)
    draw_redraw()

def random_placement(parts):
    """Randomly place parts within an appropriately-sized area.

    Args:
        parts (list): List of Parts to place.
    """

    # Compute appropriate size to hold the parts based on their areas.
    area = 0
    for part in parts:
        area += part.bbox.area
    side = 3 * math.sqrt(area) # Multiplier is ad-hoc.

    # Place parts randomly within area.
    for part in parts:
        part.tx.origin = Point(random.random() * side, random.random() * side)

def snap_to_grid(part):
    """Snap part to grid.

    Args:
        part (Part): Part to snap to grid.
    """

    if part.pins:
        pin = part.pins[0]
        pt = pin.pt.dot(part.tx)
        snap_pt = pt.snap(GRID)
        snap_tx = Tx()
        snap_tx.origin = snap_pt - pt
        part.tx = part.tx.dot(snap_tx)
    else:
        part_ctr = part.bbox.dot(part.tx).ctr
        part.tx.origin = part_ctr.snap(GRID)


speed = 0.5
speed_mult = 2.0
centroid_mult = 0
use_mass = False
ignore_power = True
use_fanout_1 = False
use_fanout_2 = False
do_snap = True


def parts_centroid(parts):
    bbox = BBox()
    for part in parts:
        bbox.add(part.bbox.dot(part.tx))
    return bbox.ctr

def gravity_force(part, centroid):
    return centroid - part.bbox.dot(part.tx).ctr

def net_force(part, nets):
    """Compute attractive force on a part from all the other parts connected to it.

    Args:
        part (Part): Part affected by forces from other connected parts.
        nets (list): List of active internal nets connecting parts.

    Returns:
        Vector: Force upon given part.
    """

    # These store the anchor points where each net attaches to the given part
    # and the pulling points where each net attaches to other parts.
    anchor_pts = defaultdict(list)
    pulling_pts = defaultdict(list)

    # Find anchor points on the part and pulling points on other parts.
    for part_pin in part.pins:
        net = part_pin.net
        if net in nets:
            # Only find anchor/pulling points on active internal nets.
            for pin in net.pins:
                if pin.part is part:
                    # Anchor parts for this net are on the given part.
                    anchor_pts[net].append(pin.pt.dot(part.tx))
                else:
                    # Everything else is a pulling point.
                    pulling_pts[net].append(pin.pt.dot(pin.part.tx))

    # Compute the combined force of all the anchor/pulling points on each net.
    total_force = Vector(0, 0)
    for net in anchor_pts.keys():

        if ignore_power:
            if net.netclass == "Power" or "vcc" in net.name.lower() or "gnd" in net.name.lower():
                continue

        if use_fanout_1:
            try:
                net_force = 1 / (len(net.pins) - 1)**3
            except ZeroDivisionError:
                net_force = 1
        elif use_fanout_2:
            if len(net.pins) > 4:
                net_force = 0
            else:
                net_force = 1
        else:
            net_force = 1

        for anchor_pt in anchor_pts[net]:
            for pulling_pt in pulling_pts[net]:
                # Force from pulling to anchor point is proportional to distance.
                total_force += (pulling_pt - anchor_pt) * net_force

    if use_mass:
        return total_force / len(part.pins)
    else:
        return total_force

def overlap_force(part, parts):
    """Compute the repulsive force on a part from overlapping other parts.

    Args:
        part (Part): Part affected by forces from other overlapping parts.
        parts (list): List of parts to check for overlaps.

    Returns:
        Vector: Force upon given part.
    """

    part_bbox = part.bbox.dot(part.tx)
    total_force = Vector(0, 0)
    for other_part in set(parts) - {part}:
        # Repulsion is proportional to the square-root of the area of the intersecting bboxes.
        # This keeps it commensurate with the attractive net forces.
        other_part_bbox = other_part.bbox.dot(other_part.tx)
        intersection_bbox = other_part_bbox.intersection(part_bbox)
        repulsion = math.sqrt(intersection_bbox.area)

        # Force direction is from the center of the intersection to the part's center.
        direction = (part_bbox.ctr - intersection_bbox.ctr).norm

        # Push in the direction most likely to clear the overlap.
        # If the intersection is wider than high, only push vertically.
        # Otherwise, push horizontally if taller than wide.
        if intersection_bbox.w > intersection_bbox.h:
            direction.x = 0
        else:
            direction.y = 0

        # Add repulsion for this intersection to the total force.
        total_force += direction * repulsion
    return total_force

def total_force(part, parts, nets, centroid, alpha):
    """Compute the total of the net attractive and overlap repulsive forces on a part.

    Args:
        part (Part): Part affected by forces from other overlapping parts.
        parts (list): List of parts to check for overlaps.
        nets (list): List of nets connecting parts.
        alpha (float): Proportion of the total that is the overlap force (range [0,1]).

    Returns:
        Vector: Weighted total of net attractive and overlap repulsion forces.
    """
    return (1 - alpha) * (net_force(part, nets) + centroid_mult * gravity_force(part, centroid)) + alpha * overlap_force(part, parts)

def adjust_orientations(parts, nets, alpha):
    for part in parts:
        smallest_force = float("inf")
        for i in range(2):
            for j in range(4):
                force = total_force(part, parts, nets, alpha)
                if force.magnitude < smallest_force:
                    smallest_force = frc.magnitude
                    smallest_tx = copy(part.tx)
                part.tx.rot_cw_90()
            part.tx.flip_x()
        part.tx = smallest_tx

def push_and_pull(parts, nets, centroid, speed, scr, tx, font):
    """Move parts under influence of attracting nets and repulsive part overlaps.

    Args:
        parts (list): List of Parts.
        nets (list): List of nets that interconnect parts.
        scr (PyGame screen): Screen object for PyGame debug drawing.
        tx (Tx): Transformation matrix from real to screen coords.
        font (PyGame font): Font for rendering text.
    """

    unshuffled_parts = parts[:]

    # Arrange parts under influence of net attractions and part overlaps.
    num_iters = round(100 / speed)
    for alpha in range(num_iters):
        random.shuffle(parts)
        for part in parts:
            force = total_force(part, parts, nets, centroid, alpha/num_iters)
            mv_dist = force * 0.5 * speed # 0.5 is ad-hoc.
            mv_tx = Tx(dx=mv_dist.x, dy=mv_dist.y)
            part.tx = part.tx.dot(mv_tx)
        if scr:
            draw_placement(unshuffled_parts, nets, scr, tx, font)

def remove_overlaps(parts, nets, scr, tx, font):
    """Remove any overlaps using horz/vert grid movements.

    Args:
        parts (list): List of Parts.
        nets (list): List of nets that interconnect parts.
        scr (PyGame screen): Screen object for PyGame debug drawing.
        tx (Tx): Transformation matrix from real to screen coords.
        font (PyGame font): Font for rendering text.
    """

    unshuffled_parts = parts[:]

    overlaps = True
    while overlaps:
        overlaps = False
        random.shuffle(parts)
        for part in parts:
            shove_force = overlap_force(part, parts)
            if shove_force.magnitude > 0:
            # if shove_force.magnitude > GRID:
                overlaps = True
                shove_tx = Tx()
                if shove_force.x < 0:
                    shove_tx.dx = -GRID
                elif shove_force.x > 0:
                    shove_tx.dx = GRID
                if shove_force.y < 0:
                    shove_tx.dy = -GRID
                elif shove_force.y > 0:
                    shove_tx.dy = GRID
                part.tx = part.tx.dot(shove_tx)
        if scr:
            draw_placement(unshuffled_parts, nets, scr, tx, font)

def slip_and_slide(parts, nets, scr, tx, font):
    """Move parts on horz/vert grid looking for improvements without causing overlaps.
    
    Args:
        parts (list): List of Parts.
        nets (list): List of nets that interconnect parts.
        scr (PyGame screen): Screen object for PyGame debug drawing.
        tx (Tx): Transformation matrix from real to screen coords.
        font (PyGame font): Font for rendering text.
    """

    unshuffled_parts = parts[:]

    moved = True
    while moved:
        moved = False
        random.shuffle(parts)
        for part in parts:
            smallest_force = net_force(part, nets).magnitude
            original_tx = part.tx
            best_tx = original_tx
            for dx, dy in ((-GRID, 0), (GRID, 0), (0, -GRID), (0, GRID)):
                mv_tx = Tx(dx=dx, dy=dy)
                part.tx = original_tx.dot(mv_tx)
                force = net_force(part, nets).magnitude
                if force < smallest_force:
                    if overlap_force(part, parts).magnitude == 0:
                        smallest_force = force
                        best_tx = part.tx
                        moved = True
            part.tx = best_tx
        if scr:
            draw_placement(unshuffled_parts, nets, scr, tx, font)

def evolve_placement(parts, nets, speed=1.0, scr=None, tx=None, font=None):
    """Evolve part placement looking for optimum.
    
    Args:
        parts (list): List of Parts.
        nets (list): List of nets that interconnect parts.
        scr (PyGame screen): Screen object for PyGame debug drawing.
        tx (Tx): Transformation matrix from real to screen coords.
        font (PyGame font): Font for rendering text.
    """

    centroid = parts_centroid(parts)

    # Force-directed placement.
    push_and_pull(parts, nets, centroid, speed, scr, tx, font)

    # Snap parts to grid.
    if do_snap:
        for part in parts:
            snap_to_grid(part)

    # Remove part overlaps.
    remove_overlaps(parts, nets, scr, tx, font)

    # Look for local improvements.
    slip_and_slide(parts, nets, scr, tx, font)


def place(node, flags=["draw"]):
    """Place the parts in the node.

    Steps:
        1. ...
        2. ...

    Args:
        node (Node): Hierarchical node containing the parts to be placed.
        flags (list): List of text flags to control drawing of placement
            for debugging purposes. Available flags are "draw".

    Returns:
        The Node with the part positions set.
    """

    # Exit if no parts to route.
    if not node.parts:
        return node

    # Extract list of nets internal to the node for routing.
    processed_nets = []
    internal_nets = []
    for part in node.parts:
        for part_pin in part:

            # A label means net is stubbed so there won't be any explicit wires.
            if len(part_pin.label) > 0:
                continue

            # No explicit wires if the pin is not connected to anything.
            if not part_pin.is_connected():
                continue

            net = part_pin.net

            if net in processed_nets:
                continue

            processed_nets.append(net)

            # No explicit wires for power nets.
            if net.netclass == "Power":
                continue

            def is_internal(net):

                # Determine if all the pins on this net reside in the node.
                for net_pin in net.pins:

                    # Don't consider stubs.
                    if len(net_pin.label) > 0:
                        continue

                    # If a pin is outside this node, then the net is not internal.
                    if net_pin.part.hierarchy != part_pin.part.hierarchy:
                        return False

                # All pins are within the node, so the net is internal.
                return True

            if is_internal(net):
                internal_nets.append(net)

    # Exit if no nets to route.
    if not internal_nets:
        pass

    random_placement(node.parts)

    # If enabled, draw the global and detailed routing for debug purposes.
    if "draw" in flags:
        bbox = BBox()
        for part in node.parts:
            tx_bbox = part.bbox.dot(part.tx)
            bbox.add(tx_bbox)
        draw_scr, draw_tx, draw_font = draw_start(bbox)
        evolve_placement(node.parts, internal_nets, speed=speed, scr=draw_scr, tx=draw_tx, font=draw_font)
        evolve_placement(node.parts, internal_nets, speed=speed*speed_mult, scr=draw_scr, tx=draw_tx, font=draw_font)
        draw_end()
    else:
        evolve_placement(node.parts, internal_nets, speed=speed)
        evolve_placement(node.parts, internal_nets, speed=speed*speed_mult)

    return node
