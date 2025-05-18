# Instalační skript pro mnd_spi_app 
from setuptools import setup, find_packages

setup(
    name="lesni_inventarizace",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "geopandas>=0.10.0",
        "pandas>=1.3.0",
        "numpy>=1.20.0",
        "matplotlib>=3.4.0",
        "shapely>=1.8.0",
        "pyyaml>=6.0",
        "jupyter>=1.0.0",
        "fiona>=1.8.20",
    ],
    python_requires=">=3.8",
    author="Robert Blaha",
	organization="Mendelova univerzita v Brně",
    author_email="robert.blaha@rbc.cz",
    description="Aplikace pro výpočet ukazatelů statistické inventarizace lesa",
    keywords="les, inventarizace, gis, geopackage",
    url="https://github.com/vas-repozitar/lesni-inventarizace",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
        "Programming Language :: Python :: 3",
        "Topic :: Scientific/Engineering :: GIS",
    ],
)