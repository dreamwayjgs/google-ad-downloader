import configparser
import os


def load_config(filename="config.ini") -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    abs_path = os.path.abspath(filename)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"설정 파일이 존재하지 않음: {abs_path}")
    config.read(abs_path, encoding="utf-8")
    return config
