"""
Seed script — generates sample data for this project.
Run: python data/seed.py

This creates realistic sample CSV files for running the app without a database.
"""

import csv
import random
import os
from datetime import datetime, timedelta

random.seed(42)  # Reproducible data

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


def random_date(start, end):
    """Generate a random date between start and end."""
    delta = end - start
    random_days = random.randint(0, delta.days)
    return start + timedelta(days=random_days)


def generate_sample_data():
    """Generate all sample CSV files."""
    print("Generating sample data...")

    # TODO: This function will be customized per project
    # based on the data profile. The agent will fill in
    # the actual generation logic during anonymization.

    print(f"Sample data written to {OUTPUT_DIR}/")


if __name__ == "__main__":
    generate_sample_data()
