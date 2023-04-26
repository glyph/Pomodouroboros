@unique
class Shape(Enum):
    RING = auto()
    BAR = auto()
    DISK = auto()

@unique
class Direction(Flag):
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()
    CENTER = 0

class Kind(Enum):
    BREAK
    I


@dataclass
class Toggl:
    keyring_handle: str
    workspace_id: str
    project_ids: Mapping[IntervalType, str]
    tags: Mapping[IntervalType, Sequence[str]]

    machine_id: str
    lastSynced: datetime.datetime

    # methods for configuration ~load/save

    def setupIntegration(self, nexus):
        nexus.addIntervalListener(self)
        # * IntervalListener
        # * IntentionListener
        ...

    # some methods for UI listener protocol


@dataclass(frozen=True)
class AvailableIntegration:
    name: str
    api_url: str # tbd

    @classmethod
    def fromJSONable(cls, details):
        return cls(**details)

    def toJSONable(self):
        return attrs.asdict(self) 




@dataclass(frozen=True):
class Integration:
    kind: AvailableIntegration
    username: Optional[str]
    secret_ref: str # Not the secret -- used instead of
                    # username in the keyring API:
                    # Secret is found using
                    # keyring.get_password(
                    #     "pomodoroborous_" + host_part_of(kind.api_url),
                    #     secret_ref,
                    # )

    @classmethod
    def fromJSONable(cls, details):
        return cls(**details)

    def toJSONable(self):
        ret = attrs.asdict(self) 
        ret.pop("kind")
        ret["kind"] = self.kind.toJSONable()
        return ret


@dataclass(frozen=True)
class Configuration:
   hud_shape: Shape
   hud_direction: Direction
   integrations: Sequence[Intergration]

   def toJSONable(self):
       ret = dict(
           hud_shape=self.hud_shape.name,
           hud_direction=self.hud_direction.name,
       )
       ret["integrations"] = [
           integration.toJSONable()
           for integration in integration
       ]
       return ret
