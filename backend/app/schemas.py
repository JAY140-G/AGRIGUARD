from datetime import date
from pydantic import BaseModel, Field, model_validator, ConfigDict

class Credentials(BaseModel):
    email: str = Field(min_length=3,max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    password: str = Field(min_length=10,max_length=128)

class FarmInput(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    crop: str = Field(min_length=1,max_length=80)
    planting_date: date | None = None
    boundary: dict

class PlanInput(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    altitude_m: float = Field(default=60,ge=10,le=120)
    speed_mps: float = Field(default=5,ge=.5,le=15)
    front_overlap: float = Field(default=.75,ge=0,le=.95)
    side_overlap: float = Field(default=.65,ge=0,le=.95)
    sensor_width_mm: float | None = Field(default=None,gt=0,le=100)
    focal_length_mm: float | None = Field(default=None,gt=0,le=1000)
    image_width_px: int = Field(default=4000,ge=100,le=20000)
    image_height_px: int = Field(default=3000,ge=100,le=20000)
    exclusions: list[dict] = Field(default_factory=list,max_length=30)
    @model_validator(mode='after')
    def paired(self):
        if (self.sensor_width_mm is None)!=(self.focal_length_mm is None): raise ValueError('Supply both sensor width and focal length')
        return self

class FeedbackInput(BaseModel):
    verdict: str = Field(pattern='^(confirmed|incorrect|inspection)$')

class LocationInput(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    lon: float = Field(ge=-180,le=180)
    lat: float = Field(ge=-90,le=90)

class Prediction(BaseModel):
    label: str
    score: float | None = Field(default=None,ge=0,le=1)
    model_version: str
    supported_crops: list[str]
    domain: str
    uncertain: bool
    unsupported: bool
    simulated: bool
    analysis_mode: str
