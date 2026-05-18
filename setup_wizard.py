#!/usr/bin/env python3
"""
AshaBot / BYOEB Interactive Setup Wizard

Usage:
    pip install questionary rich passlib[bcrypt]
    python setup_wizard.py
"""

from wizard.questions import ask_all
from wizard.env_generator import generate_env
from wizard.compose_helper import print_next_steps


def main():
    answers = ask_all()
    env_path = generate_env(answers)
    print_next_steps(answers, env_path)


if __name__ == "__main__":
    main()
