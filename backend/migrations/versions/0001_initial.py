"""Initial relational schema and PostGIS geographic boundary column."""
from alembic import op
from app.db import Base
revision='0001'
down_revision=None

def upgrade():
    bind=op.get_bind()
    Base.metadata.create_all(bind)
    if bind.dialect.name=='postgresql':
        op.execute('CREATE EXTENSION IF NOT EXISTS postgis')
        op.execute('ALTER TABLE farms ADD COLUMN boundary_geog geography(Polygon,4326)')
        op.execute('CREATE INDEX ix_farms_boundary_geog ON farms USING gist(boundary_geog)')

def downgrade():
    Base.metadata.drop_all(op.get_bind())
