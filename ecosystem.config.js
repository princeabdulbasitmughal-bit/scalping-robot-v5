module.exports = {
  apps: [
    {
      name: 'scalping-watchdog',
      script: 'watchdog_runner.py',
      interpreter: 'C:\\Users\\absh5\\AppData\\Local\\Programs\\Python\\Python311\\python.exe',
      cwd: 'E:\\scalping-robot-v5',
      watch: false,
      max_memory_restart: '500M',
      restart_delay: 5000,
      max_restarts: 50,
      out_file: 'E:\\scalping-robot-v5\\pm2_watchdog_out.log',
      error_file: 'E:\\scalping-robot-v5\\pm2_watchdog_err.log',
    },
    {
      name: 'tunnel-watchdog',
      script: 'tunnel_watchdog.py',
      interpreter: 'C:\\Users\\absh5\\AppData\\Local\\Programs\\Python\\Python311\\python.exe',
      cwd: 'E:\\scalping-robot-v5',
      watch: false,
      max_memory_restart: '200M',
      restart_delay: 5000,
      max_restarts: 50,
    }
  ]
};
