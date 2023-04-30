from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple, TypeVar, Protocol
from enum import unique, Enum, auto

OffsetType = TypeVar("OffsetType")
Coordinates = Tuple[OffsetType, OffsetType]
BoundingBox = Tuple[Coordinates[OffsetType], Coordinates[OffsetType]]
Grid = int
Frame = float

@unique
class HudSize(Enum):
    SMALL = auto()
    MEDIUM = auto()
    LARGE = auto()

@unique
class Position(Enum):
    BEGINNING = 0
    MIDDLE = 1
    END = 2

@dataclass(frozen=True)
class HudParameters:
    size: HudSize
    h_position: Position
    v_position: Position
    full: bool

@dataclass(frozen=True)
class RingParams:
    center: Coordinates[Frame]
    inner_radius: float
    outer_radius: float

class Size(Protocol):
    width: float
    height: float

class VisibleFrame(Protocol):
    origin: Tuple[float, float]
    size: Size


def get_drawing_params(parameters: HudParameters, frame: VisibleFrame) -> Tuple[BoundingBox[Frame], RingParams]:
    circle = _Circle.from_parameters(parameters)
    frame_values = (
        (frame.origin[0], frame.origin[1]), 
        (frame.origin[0] + frame.size.width, frame.origin[1] + frame.size.height), 
    )
    relative_box = circle.relativize(frame_values)
    (top_x, top_y), (bottom_x, bottom_y) = relative_box
    mid_x = (top_x + bottom_x) / 2
    mid_y = (top_y + bottom_y) / 2
    center = (mid_x, mid_y)
    outer_radius = mid_x - top_x
    inner_radius = 0.9 * outer_radius if not circle.full else 0
    ring_params = RingParams(center=center, outer_radius=outer_radius, inner_radius=inner_radius)
    return relative_box, ring_params


@dataclass(frozen=True)
class _Circle:
    top_x: Offset[Grid] = field(default=0)
    top_y: Offset[Grid] = field(default=0)
    bottom_x: Offset[Grid] = field(default=15)
    full: bool = field(default=False)

    @classmethod
    def from_parameters(cls, parameters: HudParameters) -> Circle:
        if parameters.size == HudSize.SMALL:
            top_x = int(parameters.h_position.value * 7.5)
            top_y = int(parameters.v_position.value * 7.5)
            bottom_x = top_x + 4
        elif parameters.size == HudSize.LARGE:
            top_x = 0
            top_y = 0
            bottom_x = top_x + 16
        elif parameters.size == HudSize.MEDIUM:
            top_x = int(parameters.h_position.value * 6)
            top_y = int(parameters.v_position.value * 6)
            bottom_x = top_x + 8
        return cls(top_x=top_x, top_y=top_y, bottom_x=bottom_x, full=parameters.full)

    @property
    def bounding_box(self) -> BoundingBox[Grid]:
        bottom_y = bottom_x + (top_y - top_x)
        return (top_x, top_y), (bottom_x, bottom_y)

    def relativize(self, frame: BoundingBox[Frame]) -> BoundingBox[Frame]:
        bottom_x, top_y, top_x, = self.bottom_x, self.top_x, self.top_y
        bottom_y = bottom_x + (top_y - top_x)
        (raw_top_x, raw_top_y), (raw_bottom_x, raw_bottom_y) = frame
        raw_x_size = raw_bottom_x - raw_top_x
        x_grid_step = raw_x_size / 16
        raw_y_size = raw_bottom_y - raw_top_y
        y_grid_step = raw_y_size / 16
        base_top_x = raw_top_x + x_grid_step * self.top_x
        base_top_y = raw_top_y + y_grid_step * self.top_y
        base_bottom_x = raw_top_x + x_grid_step * self.bottom_x
        base_bottom_y = raw_top_y + y_grid_step * bottom_y
        mid_x = (base_top_x + base_bottom_x) / 2
        mid_y = (base_top_y + base_bottom_y) / 2
        x_head_room = mid_x - base_top_x
        y_head_room = mid_y - base_top_y
        head_room = min(x_head_room, y_head_room)
        effective_head_room = 0.9 * head_room
        ret_top_x = mid_x - effective_head_room / 2
        ret_top_y = mid_y - effective_head_room / 2
        ret_bottom_x = mid_x + effective_head_room / 2
        ret_bottom_y = mid_y + effective_head_room / 2
        return (ret_top_x, ret_top_y), (ret_bottom_x, ret_bottom_y)
