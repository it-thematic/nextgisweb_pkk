import io
import os
import sys

from setuptools import setup, find_packages

with io.open('VERSION', 'r') as fd:
    VERSION = fd.read().rstrip()

requires = (
    'nextgisweb',
)

entry_points = {
    'nextgisweb.packages': [
        'nextgisweb_pkk = nextgisweb_pkk:pkginfo',
    ],

    'nextgisweb.amd_packages': [
        'nextgisweb_pkk = nextgisweb_pkk:amd_packages',
    ],

}

setup(
    name='nextgisweb_pkk',
    version=VERSION,
    description="Plugin for integration with aiorosreestr service",
    author='IT-Thematic',
    author_email='inbox@it-thematic.ru',
    url='https://github.com/it-thematic/nextgisweb_pkk',
    license='',
    packages=find_packages(exclude=['ez_setup', 'examples', 'tests']),
    include_package_data=True,
    zip_safe=False,
    install_requires=requires,
    entry_points=entry_points,
    long_description="",
    classifiers=[],
    keywords='',

)
