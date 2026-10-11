const path = require('path');

const ROOT_DIR = __dirname;
const PYTHON = process.env.PYTHON_PATH || (process.platform === 'win32'
  ? 'C:\\Users\\absh5\\AppData\\Local\\Programs\\Python\\Python311\\python.exe'
  : 'python3');

module.exports = {
  apps: [
    {
      name: 'scalping-watchdog',
      script: 'watchdog_runner.py',
      interpreter: PYTHON,
      cwd: ROOT_DIR,
      watch: false,
      max_memory_restart: '500M',
      restart_delay: 5000,
      max_restarts: 50,
      out_file: path.join(ROOT_DIR, 'pm2_watchdog_out.log'),
      error_file: path.join(ROOT_DIR, 'pm2_watchdog_err.log'),
    },
    {
      name: 'tunnel-watchdog',
      script: 'tunnel_watchdog.py',
      interpreter: PYTHON,
      cwd: ROOT_DIR,
      watch: false,
      max_memory_restart: '200M',
      restart_delay: 5000,
      max_restarts: 50,
    }
  ]
};

