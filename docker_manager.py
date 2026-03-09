"""
                      [TeamDev](https://team_x_og)
          
          Project Id -> 28.
          Project Name -> Script Host.
          Project Age -> 4Month+ (Updated On 07/03/2026)
          Project Idea By -> @MR_ARMAN_08
          Project Dev -> @MR_ARMAN_08
          Powered By -> @Team_X_Og ( On Telegram )
          Updates -> @CrimeZone_Update ( On telegram )
    
    Setup Guides -> Read > README.md Or VPS_README.md
    
          This Script Part Off https://Team_X_Og's Team.
          Copyright ©️ 2026 TeamDev | @Team_X_Og
"""

import os
import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable

# Try to import docker, but handle if not available
try:
    import docker
    from docker.errors import DockerException, BuildError, APIError, NotFound
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
    logging.warning("Docker Python package not installed. Docker functionality will be disabled.")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SLEEP_REASON_AUTO = "auto_stop_12h"
SLEEP_REASON_MANUAL = "manual_stop"
SLEEP_REASON_ABUSE = "resource_abuse"


class DockerManager:
    def __init__(self, database):
        """
        Initialize Docker Manager for VPS deployment
        
        Args:
            database: Database instance for storing project data
        """
        self.db = database
        self.monitoring_threads = {}
        self.notify_callback = None
        self.client = None  # Initialize client as None
        
        # Check if Docker should be explicitly disabled
        self.docker_disabled = os.environ.get('DISABLE_DOCKER', '').lower() == 'true'
        
        # Initialize Docker client if available and not disabled
        if DOCKER_AVAILABLE and not self.docker_disabled:
            try:
                self.client = docker.from_env()
                # Test connection
                self.client.ping()
                logger.info("✅ Docker client initialized successfully")
                logger.info(f"🐳 Docker version: {self.client.version().get('Version', 'unknown')}")
            except DockerException as e:
                logger.error(f"❌ Failed to initialize Docker client: {e}")
                logger.error("💡 Make sure Docker is installed and running: sudo systemctl start docker")
                self.client = None
                self.docker_disabled = True
            except Exception as e:
                logger.error(f"❌ Unexpected error initializing Docker: {e}")
                self.client = None
                self.docker_disabled = True
        else:
            if not DOCKER_AVAILABLE:
                logger.warning("⚠️ Docker Python package not available")
                logger.warning("💡 Install it with: pip install docker")
            if self.docker_disabled:
                logger.info("🚫 Docker explicitly disabled via DISABLE_DOCKER environment variable")
        
        # Start auto-monitor if Docker is available
        if self.client:
            self._start_auto_monitor()
            # Start periodic cleanup
            self._start_cleanup_scheduler()

    def _notify(self, user_id, message_text):
        """Send notification to user via callback"""
        if self.notify_callback:
            try:
                self.notify_callback(user_id, message_text)
            except Exception as e:
                logger.error(f"[Notify] Error notifying {user_id}: {e}")

    def _check_docker_available(self, operation: str) -> bool:
        """
        Check if Docker is available for operations
        
        Args:
            operation: Name of operation being attempted
            
        Returns:
            bool: True if Docker is available, False otherwise
        """
        if not self.client:
            logger.warning(f"Docker not available for operation: {operation}")
            return False
        return True

    def deploy_project(self, user_id, project_name, project_dir, limits):
        """
        Deploy a project in a Docker container
        
        Args:
            user_id: Telegram user ID
            project_name: Name of the project
            project_dir: Directory containing project files
            limits: Resource limits (cpu, memory, etc.)
            
        Returns:
            dict: Deployment result with success/error info
        """
        if not self._check_docker_available("deploy_project"):
            return {
                'success': False, 
                'error': 'Docker is not available. Please ensure Docker is installed and running on your VPS.'
            }

        try:
            # Find Dockerfile
            dockerfile_path = None
            for root, dirs, files in os.walk(project_dir):
                if 'Dockerfile' in files:
                    dockerfile_path = root
                    break

            if not dockerfile_path:
                return {'success': False, 'error': 'Dockerfile not found in the uploaded files'}

            # Generate image tag
            image_tag = f"user_{user_id}_{project_name}".lower().replace(' ', '_').replace('-', '_')
            logger.info(f"[Deploy] Building image: {image_tag}")

            # Build Docker image
            try:
                image, build_logs = self.client.images.build(
                    path=dockerfile_path,
                    tag=image_tag,
                    rm=True,
                    nocache=False
                )
            except BuildError as e:
                error_msg = str(e)
                if hasattr(e, 'build_log'):
                    error_lines = []
                    for log in e.build_log:
                        if 'error' in str(log).lower():
                            error_lines.append(str(log))
                    if error_lines:
                        error_msg = '\n'.join(error_lines[-3:])
                return {'success': False, 'error': f"Build failed: {error_msg}"}

            # Process build logs
            build_output = []
            for log in build_logs:
                if 'stream' in log:
                    build_output.append(log['stream'].strip())

            # Run container
            container_name = f"{image_tag}_{int(time.time())}"
            
            # Prepare container run arguments
            run_kwargs = {
                'detach': True,
                'name': container_name,
                'cpu_quota': int(limits.get('cpu_cores', 1) * 100000),
                'mem_limit': f"{limits.get('memory', 512)}m",
                'network_mode': 'bridge',
                'labels': {
                    'user_id': str(user_id),
                    'project_name': project_name,
                    'tier': limits.get('tier', 'free'),
                    'deployed_at': str(datetime.now())
                }
            }
            
            # Add restart policy if specified
            if limits.get('restart_on_crash', False):
                run_kwargs['restart_policy'] = {
                    "Name": "on-failure",
                    "MaximumRetryCount": 5
                }

            container = self.client.containers.run(image_tag, **run_kwargs)
            
            logger.info(f"✅ Container {container.id} started successfully")

            # Start monitoring thread
            self.start_monitoring(user_id, project_name, limits)

            return {
                'success': True,
                'container_id': container.id,
                'container_name': container_name,
                'image_tag': image_tag,
                'build_logs': '\n'.join(build_output[-20:]) if build_output else "Build completed successfully"
            }

        except APIError as e:
            logger.error(f"Docker API error during deployment: {e}")
            return {'success': False, 'error': f"Docker API error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error during deployment: {e}")
            return {'success': False, 'error': f"Deployment error: {str(e)}"}

    def stop_container(self, container_id):
        """Stop a running container"""
        if not self._check_docker_available("stop_container"):
            return False
        try:
            container = self.client.containers.get(container_id)
            container.stop(timeout=10)
            logger.info(f"Container {container_id} stopped successfully")
            return True
        except NotFound:
            logger.warning(f"Container {container_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error stopping container {container_id}: {e}")
            return False

    def start_container(self, container_id):
        """Start a stopped container"""
        if not self._check_docker_available("start_container"):
            return False
        try:
            container = self.client.containers.get(container_id)
            container.start()
            logger.info(f"Container {container_id} started successfully")
            return True
        except NotFound:
            logger.warning(f"Container {container_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error starting container {container_id}: {e}")
            return False

    def restart_container(self, container_id):
        """Restart a container"""
        if not self._check_docker_available("restart_container"):
            return False
        try:
            container = self.client.containers.get(container_id)
            container.restart(timeout=10)
            logger.info(f"Container {container_id} restarted successfully")
            return True
        except NotFound:
            logger.warning(f"Container {container_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error restarting container {container_id}: {e}")
            return False

    def remove_project(self, container_id):
        """Remove a project (container and image)"""
        if not self._check_docker_available("remove_project"):
            return False
        try:
            container = self.client.containers.get(container_id)
            image_tag = container.image.tags[0] if container.image.tags else None
            
            # Stop and remove container
            try:
                container.stop(timeout=10)
            except:
                pass
            container.remove(force=True)
            
            # Remove image if exists
            if image_tag:
                try:
                    self.client.images.remove(image_tag, force=True)
                    logger.info(f"Image {image_tag} removed")
                except Exception as e:
                    logger.warning(f"Could not remove image {image_tag}: {e}")
            
            logger.info(f"Project {container_id} removed successfully")
            return True
        except NotFound:
            logger.warning(f"Container {container_id} not found")
            return True  # Return True as project is already gone
        except Exception as e:
            logger.error(f"Error removing project {container_id}: {e}")
            return False

    def get_container_stats(self, container_id):
        """Get resource usage statistics for a container"""
        if not self._check_docker_available("get_container_stats"):
            return None
        try:
            container = self.client.containers.get(container_id)
            stats = container.stats(stream=False)

            # Calculate CPU percentage
            cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                       stats['precpu_stats']['cpu_usage']['total_usage']
            system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                          stats['precpu_stats']['system_cpu_usage']
            cpu_percent = (cpu_delta / system_delta) * 100.0 if system_delta > 0 else 0
            
            # Calculate memory usage in MB
            memory_usage = stats['memory_stats'].get('usage', 0) / (1024 * 1024)
            
            # Get memory limit
            memory_limit = stats['memory_stats'].get('limit', 0) / (1024 * 1024)

            return {
                'cpu': round(cpu_percent, 2),
                'memory': round(memory_usage, 2),
                'memory_limit': round(memory_limit, 2),
                'status': container.status,
                'network_rx': stats.get('networks', {}).get('eth0', {}).get('rx_bytes', 0),
                'network_tx': stats.get('networks', {}).get('eth0', {}).get('tx_bytes', 0)
            }
        except NotFound:
            logger.warning(f"Container {container_id} not found for stats")
            return None
        except Exception as e:
            logger.error(f"Error getting stats for container {container_id}: {e}")
            return None

    def get_container_logs(self, container_id, lines=100):
        """Get logs from a container"""
        if not self._check_docker_available("get_container_logs"):
            return "Docker not available"
        try:
            container = self.client.containers.get(container_id)
            logs = container.logs(
                tail=lines,
                stdout=True,
                stderr=True,
                timestamps=False
            ).decode('utf-8', errors='ignore')
            return logs if logs.strip() else '(no output yet — container may still be starting)'
        except NotFound:
            return '(container not found — it may have been removed)'
        except Exception as e:
            return f'(could not fetch logs: {str(e)})'

    def list_containers(self, user_id=None):
        """List all containers, optionally filtered by user"""
        if not self._check_docker_available("list_containers"):
            return []
        try:
            filters = {}
            if user_id:
                filters = {'label': f'user_id={user_id}'}
            
            containers = self.client.containers.list(all=True, filters=filters)
            result = []
            for container in containers:
                labels = container.labels
                result.append({
                    'id': container.id,
                    'name': container.name,
                    'status': container.status,
                    'image': container.image.tags[0] if container.image.tags else 'unknown',
                    'user_id': labels.get('user_id'),
                    'project_name': labels.get('project_name'),
                    'tier': labels.get('tier', 'free'),
                    'created': container.attrs['Created']
                })
            return result
        except Exception as e:
            logger.error(f"Error listing containers: {e}")
            return []

    def start_monitoring(self, user_id, project_name, limits):
        """Start monitoring a container for resource usage and auto-sleep"""
        if not self._check_docker_available("start_monitoring"):
            return

        thread_key = f"{user_id}_{project_name}"
        
        # Check if monitoring already exists
        if thread_key in self.monitoring_threads:
            t = self.monitoring_threads[thread_key]
            if t and t.is_alive():
                logger.debug(f"Monitoring already active for {thread_key}")
                return
        self.monitoring_threads.pop(thread_key, None)

        def monitor():
            start_time = time.time()
            warned_1h = False
            warned_30min = False
            warned_high = False
            warned_critical = False
            last_stats_update = 0

            logger.info(f"Started monitoring {project_name} for user {user_id}")

            while True:
                try:
                    # Get project from database
                    projects = self.db.get_user_projects(user_id)
                    project = next((p for p in projects if p['name'] == project_name), None)

                    if not project:
                        logger.info(f"[Monitor] Project {project_name} deleted, stopping monitor.")
                        break

                    if project.get('status') == 'stopped':
                        logger.info(f"[Monitor] Project {project_name} stopped, ending monitor.")
                        break

                    container_id = project['container_id']

                    # Check container status
                    try:
                        container = self.client.containers.get(container_id)
                        if container.status != 'running':
                            self.db.update_project(project['_id'], {
                                'status': 'sleeping',
                                'stop_reason': 'Container exited unexpectedly',
                                'sleep_at': datetime.now()
                            })
                            self._notify(user_id,
                                f"⚠️ <b>Project Crashed!</b>\n\n"
                                f"📦 <b>{project_name}</b> has stopped unexpectedly.\n\n"
                                f"Status: {container.status}\n\n"
                                f"Use /projects to restart it."
                            )
                            break
                    except NotFound:
                        self.db.update_project(project['_id'], {
                            'status': 'sleeping',
                            'stop_reason': 'Container not found',
                            'sleep_at': datetime.now()
                        })
                        break

                    # Get and update stats
                    stats = self.get_container_stats(container_id)
                    if stats:
                        uptime_hours = (time.time() - start_time) / 3600
                        
                        # Update database with usage (throttled to reduce writes)
                        if time.time() - last_stats_update > 60:  # Update every minute
                            self.db.update_project(project['_id'], {
                                'usage': {
                                    'cpu': stats['cpu'],
                                    'memory': stats['memory'],
                                    'uptime': round(uptime_hours, 2)
                                },
                                'status': 'running'
                            })
                            last_stats_update = time.time()

                        # Auto-stop after specified hours
                        if limits.get('auto_stop') and uptime_hours >= limits['auto_stop']:
                            self.stop_container(container_id)
                            self.db.update_project(project['_id'], {
                                'status': 'sleeping',
                                'stop_reason': SLEEP_REASON_AUTO,
                                'sleep_at': datetime.now()
                            })
                            self._notify(user_id,
                                                                 f"😴 <b>Project Put To Sleep</b>\n\n"
                                f"📦 <b>{project_name}</b> has been put to sleep after <b>{limits['auto_stop']} hours</b> of runtime.\n\n"
                                f"▶️ You can <b>wake it up</b> anytime from /projects\n\n"
                                f"⭐ Upgrade to /premium for higher limits!"
                            )
                            break

                        # Send warnings for approaching auto-stop
                        if limits.get('auto_stop'):
                            remaining_hours = limits['auto_stop'] - uptime_hours
                            if remaining_hours <= 1.0 and not warned_1h:
                                warned_1h = True
                                self._notify(user_id,
                                    f"⏰ <b>Sleep Warning — 1 Hour Left</b>\n\n"
                                    f"📦 <b>{project_name}</b> will go to sleep in ~<b>1 hour</b>.\n\n"
                                    f"⭐ /premium for higher limits!"
                                )
                            elif remaining_hours <= 0.5 and not warned_30min:
                                warned_30min = True
                                self._notify(user_id,
                                    f"⏰ <b>Sleep Warning — 30 Minutes Left</b>\n\n"
                                    f"📦 <b>{project_name}</b> will sleep in ~<b>30 minutes</b>.\n\n"
                                    f"⭐ /premium for higher limits!"
                                )

                        # Resource abuse detection
                        if stats['cpu'] > 85 and not warned_high:
                            warned_high = True
                            self._notify(user_id,
                                f"⚠️ <b>High CPU Usage!</b>\n\n"
                                f"📦 <b>{project_name}</b> is using <b>{stats['cpu']}% CPU</b>.\n\n"
                                f"If this continues, the project may be stopped automatically."
                            )

                        if stats['cpu'] > 92 and not warned_critical:
                            warned_critical = True
                            user = self.db.get_user(user_id)
                            warnings_so_far = user.get('warnings', 0) if user else 0
                            self._notify(user_id,
                                f"🚨 <b>CRITICAL — Project About To Be Killed!</b>\n\n"
                                f"📦 <b>{project_name}</b> is using <b>{stats['cpu']}% CPU</b>.\n\n"
                                f"⛔ If usage doesn't drop immediately, your project will be <b>force stopped</b> "
                                f"and a warning will be added to your account.\n\n"
                                f"⚠️ Current warnings: <b>{warnings_so_far}/3</b> — 3 warnings = permanent ban.\n\n"
                                f"💡 Optimize your code or upgrade to /premium for higher limits."
                            )

                        # Kill for extreme resource usage
                        if stats['cpu'] > 95 or stats['memory'] > limits.get('memory', 512):
                            self.stop_container(container_id)
                            self.db.update_project(project['_id'], {
                                'status': 'sleeping',
                                'stop_reason': SLEEP_REASON_ABUSE,
                                'sleep_at': datetime.now()
                            })
                            self.db.add_warning(user_id, "Project killed: extreme resource usage")
                            user = self.db.get_user(user_id)
                            total_warnings = user.get('warnings', 0) if user else 0
                            
                            if total_warnings >= 3:
                                warn_msg = "🚫 <b>Project Killed — You Have Been Banned!</b>\n\n"
                            elif total_warnings == 2:
                                warn_msg = "🚫 <b>Project Killed — 1 More Warning = Permanent Ban!</b>\n\n"
                            else:
                                warn_msg = "🚫 <b>Project Killed — Resource Abuse</b>\n\n"
                            
                            self._notify(user_id,
                                f"{warn_msg}"
                                f"📦 <b>{project_name}</b> was stopped for extreme resource usage.\n"
                                f"CPU: {stats['cpu']}% | RAM: {stats['memory']}MB\n\n"
                                f"⚠️ Warnings: <b>{total_warnings}/3</b> — 3 warnings = permanent ban.\n\n"
                                f"💡 Optimize your code or upgrade to /premium for higher limits."
                            )
                            break

                    time.sleep(30)

                except Exception as e:
                    logger.error(f"[Monitor] Error: {e}")
                    time.sleep(30)

            # Clean up monitoring thread reference
            self.monitoring_threads.pop(thread_key, None)
            logger.info(f"Stopped monitoring {project_name} for user {user_id}")

        # Start monitoring thread
        thread = threading.Thread(target=monitor, daemon=True, name=f"monitor_{thread_key}")
        thread.start()
        self.monitoring_threads[thread_key] = thread

    def _start_auto_monitor(self):
        """Start automatic monitoring for all running projects"""
        def auto_monitor():
            while True:
                try:
                    running_projects = self.db.get_all_running_projects()
                    for project in running_projects:
                        thread_key = f"{project['user_id']}_{project['name']}"
                        existing = self.monitoring_threads.get(thread_key)
                        if not existing or not existing.is_alive():
                            self.start_monitoring(project['user_id'], project['name'], project.get('limits', {}))
                    time.sleep(60)
                except Exception as e:
                    logger.error(f"[AutoMonitor] Error: {e}")
                    time.sleep(60)

        thread = threading.Thread(target=auto_monitor, daemon=True, name="auto_monitor")
        thread.start()
        logger.info("✅ Auto-monitor thread started")

    def _start_cleanup_scheduler(self):
        """Start periodic cleanup of stopped containers"""
        def cleanup_scheduler():
            while True:
                try:
                    time.sleep(3600)  # Run every hour
                    self.cleanup_stopped_containers()
                except Exception as e:
                    logger.error(f"[Cleanup] Error: {e}")

        thread = threading.Thread(target=cleanup_scheduler, daemon=True, name="cleanup_scheduler")
        thread.start()
        logger.info("✅ Cleanup scheduler started")

    def cleanup_stopped_containers(self, older_than_hours=24):
        """Clean up stopped containers older than specified hours"""
        if not self._check_docker_available("cleanup_stopped_containers"):
            return
        try:
            containers = self.client.containers.list(all=True, filters={'status': 'exited'})
            cutoff_time = datetime.now() - timedelta(hours=older_than_hours)
            
            for container in containers:
                # Check if container has user_id label (managed by bot)
                if 'user_id' in container.labels:
                    created = datetime.fromisoformat(container.attrs['Created'].replace('Z', '+00:00'))
                    if created < cutoff_time:
                        container.remove()
                        logger.info(f"Cleaned up stopped container {container.id}")
        except Exception as e:
            logger.error(f"Error cleaning up containers: {e}")


class RenderManager:
    """Render.com hosting manager for deploying projects on Render"""
    
    def __init__(self, database):
        self.db = database
        self.api_key = os.environ.get('RENDER_API_KEY')
        self.owner_id = os.environ.get('RENDER_OWNER_ID')
        self.monitoring_threads = {}
        self.notify_callback = None
        
        # Check if Render is configured
        self.render_available = bool(self.api_key and self.owner_id)
        
        if self.render_available:
            logger.info("✅ Render.com integration configured")
            self.base_url = "https://api.render.com/v1"
            self.headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
        else:
            logger.warning("⚠️ Render.com not configured. Set RENDER_API_KEY and RENDER_OWNER_ID env vars.")

    def _notify(self, user_id, message_text):
        """Send notification to user via callback"""
        if self.notify_callback:
            try:
                self.notify_callback(user_id, message_text)
            except Exception as e:
                logger.error(f"[Notify] Error notifying {user_id}: {e}")

    def _check_render_available(self, operation: str) -> bool:
        """Check if Render is available for operations"""
        if not self.render_available:
            logger.warning(f"Render not available for operation: {operation}")
            return False
        return True

    def deploy_project(self, user_id, project_name, project_dir, limits):
        """
        Deploy a project on Render.com
        
        Args:
            user_id: Telegram user ID
            project_name: Name of the project
            project_dir: Directory containing project files
            limits: Resource limits (tier, etc.)
            
        Returns:
            dict: Deployment result with success/error info
        """
        if not self._check_render_available("deploy_project"):
            return {
                'success': False,
                'error': 'Render.com is not configured. Please set RENDER_API_KEY and RENDER_OWNER_ID.'
            }

        try:
            # Check for render.yaml or dockerfile
            has_render_yaml = os.path.exists(os.path.join(project_dir, 'render.yaml'))
            has_dockerfile = os.path.exists(os.path.join(project_dir, 'Dockerfile'))
            
            if not (has_render_yaml or has_dockerfile):
                return {
                    'success': False,
                    'error': 'No render.yaml or Dockerfile found in the uploaded files'
                }

            # Create a unique service name
            service_name = f"user-{user_id}-{project_name}".lower().replace('_', '-').replace(' ', '-')
            
            # Determine service type and plan
            plan = limits.get('render_plan', 'free')
            if plan not in ['free', 'starter', 'pro', 'pro_plus', 'pro_max']:
                plan = 'free'
            
            # Prepare service configuration
            service_config = {
                "name": service_name,
                "ownerId": self.owner_id,
                "type": "web_service",  # Default to web service
                "plan": plan,
                "envVars": [
                    {"key": "USER_ID", "value": str(user_id)},
                    {"key": "PROJECT_NAME", "value": project_name},
                    {"key": "DEPLOYED_FROM", "value": "telegram_bot"}
                ]
            }

            # Check if it's a static site
            if os.path.exists(os.path.join(project_dir, 'index.html')):
                service_config["type"] = "static_site"
                service_config["buildCommand"] = limits.get('build_command', 'echo "Static site"')
                service_config["publishPath"] = limits.get('publish_path', '.')
            else:
                # Web service with Docker or build command
                if has_dockerfile:
                    service_config["dockerfilePath"] = "./Dockerfile"
                else:
                    service_config["buildCommand"] = limits.get('build_command', 'pip install -r requirements.txt')
                    service_config["startCommand"] = limits.get('start_command', 'gunicorn app:app')

            # Create service on Render
            response = requests.post(
                f"{self.base_url}/services",
                headers=self.headers,
                json=service_config,
                timeout=30
            )

            if response.status_code not in [200, 201]:
                error_msg = response.json().get('message', 'Unknown error')
                return {
                    'success': False,
                    'error': f"Render API error: {error_msg}"
                }

            service_data = response.json()
            service_id = service_data.get('id')

            # Trigger initial deployment
            deploy_response = requests.post(
                f"{self.base_url}/services/{service_id}/deploys",
                headers=self.headers,
                json={},
                timeout=30
            )

            if deploy_response.status_code not in [200, 201]:
                logger.warning(f"Initial deploy failed: {deploy_response.text}")

            # Store deployment info
            deployment_info = {
                'service_id': service_id,
                'service_name': service_name,
                'service_url': f"https://{service_name}.onrender.com",
                'plan': plan,
                'type': service_config['type'],
                'created_at': datetime.now().isoformat()
            }

            logger.info(f"✅ Project {project_name} deployed on Render: {service_id}")

            return {
                'success': True,
                'service_id': service_id,
                'service_name': service_name,
                'service_url': deployment_info['service_url'],
                'deployment_info': deployment_info
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"Render API request error: {e}")
            return {'success': False, 'error': f"Render API error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error deploying to Render: {e}")
            return {'success': False, 'error': f"Deployment error: {str(e)}"}

    def get_service_status(self, service_id):
        """Get status of a Render service"""
        if not self._check_render_available("get_service_status"):
            return None
        
        try:
            response = requests.get(
                f"{self.base_url}/services/{service_id}",
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code == 200:
                service = response.json()
                
                # Get latest deployment
                deploys_response = requests.get(
                    f"{self.base_url}/services/{service_id}/deploys?limit=1",
                    headers=self.headers,
                    timeout=30
                )
                
                latest_deploy = {}
                if deploys_response.status_code == 200:
                    deploys = deploys_response.json()
                    if deploys:
                        latest_deploy = deploys[0]
                
                return {
                    'id': service.get('id'),
                    'name': service.get('name'),
                    'status': service.get('serviceDetails', {}).get('state', 'unknown'),
                    'url': service.get('serviceDetails', {}).get('url'),
                    'plan': service.get('plan'),
                    'suspended': service.get('suspended', 'not_suspended'),
                    'deploy_status': latest_deploy.get('status', 'unknown'),
                    'deploy_url': latest_deploy.get('url')
                }
            else:
                logger.error(f"Failed to get service status: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting service status: {e}")
            return None

    def stop_service(self, service_id):
        """Suspend a Render service"""
        if not self._check_render_available("stop_service"):
            return False
        
        try:
            response = requests.post(
                f"{self.base_url}/services/{service_id}/suspend",
                headers=self.headers,
                timeout=30
            )
            
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error suspending service: {e}")
            return False

    def start_service(self, service_id):
        """Resume a suspended Render service"""
        if not self._check_render_available("start_service"):
            return False
        
        try:
            response = requests.post(
                f"{self.base_url}/services/{service_id}/resume",
                headers=self.headers,
                timeout=30
            )
            
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error resuming service: {e}")
            return False

    def delete_service(self, service_id):
        """Delete a Render service"""
        if not self._check_render_available("delete_service"):
            return False
        
        try:
            response = requests.delete(
                f"{self.base_url}/services/{service_id}",
                headers=self.headers,
                timeout=30
            )
            
            return response.status_code == 204
        except Exception as e:
            logger.error(f"Error deleting service: {e}")
            return False

    def get_service_logs(self, service_id, lines=100):
        """Get logs from a Render service"""
        if not self._check_render_available("get_service_logs"):
            return "Render not available"
        
        try:
            response = requests.get(
                f"{self.base_url}/services/{service_id}/deploys",
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code == 200:
                deploys = response.json()
                if deploys:
                    # Get logs from latest deploy
                    deploy_id = deploys[0].get('id')
                    logs_response = requests.get(
                        f"{self.base_url}/services/{service_id}/deploys/{deploy_id}/logs",
                        headers=self.headers,
                        timeout=30
                    )
                    
                    if logs_response.status_code == 200:
                        logs = logs_response.json()
                        return logs.get('logs', 'No logs available')
            
            return "Unable to fetch logs"
            
        except Exception as e:
            return f"Error fetching logs: {str(e)}"


class HybridDeploymentManager:
    """
    Manager that handles both Docker (VPS) and Render.com deployments
    Automatically detects environment and available services
    """
    
    def __init__(self, database):
        self.db = database
        self.notify_callback = None
        
        # Initialize both managers
        self.docker_manager = DockerManager(database)
        self.render_manager = RenderManager(database)
        
        # Determine available deployment methods
        self.deployment_methods = []
        
        if self.docker_manager.client:
            self.deployment_methods.append({
                'name': 'docker',
                'description': 'Docker on VPS',
                'manager': self.docker_manager,
                'available': True
            })
        
        if self.render_manager.render_available:
            self.deployment_methods.append({
                'name': 'render',
                'description': 'Render.com Cloud',
                'manager': self.render_manager,
                'available': True
            })
        
        if self.deployment_methods:
            logger.info(f"✅ Available deployment methods: {[m['name'] for m in self.deployment_methods]}")
        else:
            logger.error("❌ No deployment methods available!")
            logger.error("   - For Docker: Install Docker and docker-py")
            logger.error("   - For Render: Set RENDER_API_KEY and RENDER_OWNER_ID")
    
    def set_notify_callback(self, callback):
        """Set notification callback for both managers"""
        self.notify_callback = callback
        self.docker_manager.notify_callback = callback
        self.render_manager.notify_callback = callback
    
    def get_available_methods(self):
        """Get list of available deployment methods"""
        return self.deployment_methods
    
    def deploy_project(self, user_id, project_name, project_dir, limits, method='auto'):
        """
        Deploy a project using specified method
        
        Args:
            user_id: Telegram user ID
            project_name: Name of the project
            project_dir: Directory containing project files
            limits: Resource limits
            method: 'docker', 'render', or 'auto'
        
        Returns:
            dict: Deployment result
        """
        if method == 'auto':
            # Auto-select based on available methods and project type
            if self.render_manager.render_available:
                # Check if project has render.yaml
                if os.path.exists(os.path.join(project_dir, 'render.yaml')):
                    return self.render_manager.deploy_project(user_id, project_name, project_dir, limits)
            
            if self.docker_manager.client:
                return self.docker_manager.deploy_project(user_id, project_name, project_dir, limits)
            
            return {'success': False, 'error': 'No deployment method available'}
        
        elif method == 'docker':
            return self.docker_manager.deploy_project(user_id, project_name, project_dir, limits)
        
        elif method == 'render':
            return self.render_manager.deploy_project(user_id, project_name, project_dir, limits)
        
        else:
            return {'success': False, 'error': f'Unknown deployment method: {method}'}
    
    def stop_project(self, project, method=None):
        """Stop a project based on its deployment method"""
        if not method and 'deployment_type' in project:
            method = project['deployment_type']
        
        if method == 'docker':
            return self.docker_manager.stop_container(project['container_id'])
        elif method == 'render':
            return self.render_manager.stop_service(project['service_id'])
        else:
            return False
    
    def start_project(self, project, method=None):
        """Start a project based on its deployment method"""
        if not method and 'deployment_type' in project:
            method = project['deployment_type']
        
        if method == 'docker':
            return self.docker_manager.start_container(project['container_id'])
        elif method == 'render':
            return self.render_manager.start_service(project['service_id'])
        else:
            return False
    
    def delete_project(self, project, method=None):
        """Delete a project based on its deployment method"""
        if not method and 'deployment_type' in project:
            method = project['deployment_type']
        
        if method == 'docker':
            return self.docker_manager.remove_project(project['container_id'])
        elif method == 'render':
            return self.render_manager.delete_service(project['service_id'])
        else:
            return False
    
    def get_project_logs(self, project, method=None, lines=100):
        """Get logs from a project"""
        if not method and 'deployment_type' in project:
            method = project['deployment_type']
        
        if method == 'docker':
            return self.docker_manager.get_container_logs(project['container_id'], lines)
        elif method == 'render':
            return self.render_manager.get_service_logs(project['service_id'], lines)
        else:
            return "Unknown deployment method"
    
    def get_project_stats(self, project, method=None):
        """Get stats from a project"""
        if not method and 'deployment_type' in project:
            method = project['deployment_type']
        
        if method == 'docker':
            return self.docker_manager.get_container_stats(project['container_id'])
        elif method == 'render':
            return self.render_manager.get_service_status(project['service_id'])
        else:
            return None
        
