from setuptools import setup, find_packages

setup(
    name="promptgenie",
    version="1.0.0",
    description="Secure prompt engineering for AI agents and engineering teams",
    author="Myles Agnew",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "promptgenie": ["profiles/*.yaml", "templates/*.yaml", "packs/**/*.yaml"],
    },
    install_requires=[
        "click>=8.0",
        "pyyaml>=6.0",
        "rich>=13.0",
        "tiktoken>=0.7",
    ],
    entry_points={
        "console_scripts": [
            "promptgenie=promptgenie.cli:cli",
        ],
    },
    python_requires=">=3.10",
)
