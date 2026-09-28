import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logging(log_level, log_dir):
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')
    
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Files
    app_log = os.path.join(log_dir, 'app.log')
    app_handler = RotatingFileHandler(app_log, maxBytes=5*1024*1024, backupCount=3)
    app_handler.setLevel(logging.DEBUG)
    app_handler.setFormatter(formatter)
    root_logger.addHandler(app_handler)
    
    err_log = os.path.join(log_dir, 'errors.log')
    err_handler = RotatingFileHandler(err_log, maxBytes=5*1024*1024, backupCount=3)
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(formatter)
    root_logger.addHandler(err_handler)
    
    auth_log = os.path.join(log_dir, 'auth.log')
    auth_handler = RotatingFileHandler(auth_log, maxBytes=5*1024*1024, backupCount=3)
    auth_handler.setLevel(logging.INFO)
    auth_handler.setFormatter(formatter)
    auth_logger = logging.getLogger('auth')
    auth_logger.addHandler(auth_handler)
    auth_logger.propagate = False
    
    sync_log = os.path.join(log_dir, 'sync.log')
    sync_handler = RotatingFileHandler(sync_log, maxBytes=5*1024*1024, backupCount=3)
    sync_handler.setLevel(logging.INFO)
    sync_handler.setFormatter(formatter)
    sync_logger = logging.getLogger('sync')
    sync_logger.addHandler(sync_handler)
    sync_logger.propagate = False

