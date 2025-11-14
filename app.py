"""
Flask Automated HTML Testing Application - Refactored
Install: pip install flask selenium beautifulsoup4
"""

import json
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
import threading

from flask import Flask, render_template, request, jsonify, send_file
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException

# Configuration
class Config:
    UPLOAD_FOLDER = 'test_files'
    REPORTS_FOLDER = 'test_reports'
    SCREENSHOTS_FOLDER = 'screenshots'
    RECORDINGS_FOLDER = 'recordings'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    CUSTOM_GECKO_WINDOWS = r"C:\Drivers\Firefox\geckodriver.exe"
    CUSTOM_EDGE_LINUX = r"/home/pranav/Downloads/edgedriver_linux64/msedgedriver"
    SUPPORTED_BROWSERS = ["chrome", "firefox", "edge", "all"]
    DEFAULT_TIMEOUT = 10
    ACTION_DELAY = 0.5
    ENABLE_VIDEO_RECORDING = True
    PARALLEL_EXECUTION = True
    MAX_PARALLEL_TESTS = 3

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test execution tracking
active_tests = {}
test_lock = threading.Lock()

@dataclass
class TestStatus:
    """Track test execution status"""
    test_name: str
    status: str  # 'running', 'completed', 'failed'
    progress: int
    total: int
    start_time: float
    browser: str
    
    def to_dict(self):
        return asdict(self)

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Create necessary directories
for folder in [Config.UPLOAD_FOLDER, Config.REPORTS_FOLDER, Config.SCREENSHOTS_FOLDER, Config.RECORDINGS_FOLDER]:
    Path(folder).mkdir(exist_ok=True)


class BrowserManager:
    """Manages browser driver setup and configuration"""
    
    @staticmethod
    def setup_chrome(headless: bool) -> webdriver.Chrome:
        """Setup Chrome WebDriver"""
        from selenium.webdriver.chrome.options import Options
        
        options = Options()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        
        return webdriver.Chrome(options=options)
    
    @staticmethod
    def setup_firefox(headless: bool) -> webdriver.Firefox:
        """Setup Firefox WebDriver"""
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        
        options = Options()
        if headless:
            options.add_argument("--headless")
        options.add_argument("--width=1920")
        options.add_argument("--height=1080")
        
        service_path = Config.CUSTOM_GECKO_WINDOWS
        service = Service(service_path) if os.name == "nt" and Path(service_path).exists() else Service()
        
        return webdriver.Firefox(service=service, options=options)
    
    @staticmethod
    def setup_edge(headless: bool) -> webdriver.Edge:
        """Setup Edge WebDriver"""
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.edge.service import Service
        
        options = Options()
        
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        
        # Linux-specific Edge driver configuration
        service_path = Config.CUSTOM_EDGE_LINUX
        if os.name != "nt" and Path(service_path).exists():
            if not os.access(service_path, os.X_OK):
                logger.warning(f"Edge driver not executable. Run: chmod +x {service_path}")
            service = Service(executable_path=service_path)
        else:
            service = Service()
        
        return webdriver.Edge(service=service, options=options)


class ActionExecutor:
    """Executes individual test actions"""
    
    def __init__(self, driver: webdriver.Remote):
        self.driver = driver
        self.variables = {}  # Store variables for later use
    
    def execute(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single test action and return result"""
        result = {
            'action': action['type'],
            'selector': action.get('selector', ''),
            'status': 'failed',
            'message': '',
            'timestamp': datetime.now().isoformat(),
            'screenshot': None
        }
        
        try:
            action_type = action['type']
            handler = getattr(self, f"_handle_{action_type}", None)
            
            if handler:
                handler(action, result)
            else:
                result['message'] = f"Unknown action type: {action_type}"
                
        except Exception as e:
            result['message'] = str(e)
            result['screenshot'] = self._capture_screenshot(action)
            logger.error(f"Action failed - {action.get('type')}: {e}")
        
        return result
    
    def _handle_click(self, action: Dict, result: Dict) -> None:
        """Handle click action"""
        element = WebDriverWait(self.driver, Config.DEFAULT_TIMEOUT).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, action['selector']))
        )
        element.click()
        result['status'] = 'passed'
        result['message'] = 'Element clicked successfully'
    
    def _handle_input(self, action: Dict, result: Dict) -> None:
        """Handle input action"""
        element = WebDriverWait(self.driver, Config.DEFAULT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, action['selector']))
        )
        element.clear()
        value = self._substitute_variables(action['value'])
        element.send_keys(value)
        result['status'] = 'passed'
        result['message'] = f"Input value: '{value}'"
    
    def _handle_select(self, action: Dict, result: Dict) -> None:
        """Handle select dropdown action"""
        element = WebDriverWait(self.driver, Config.DEFAULT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, action['selector']))
        )
        Select(element).select_by_value(action['value'])
        result['status'] = 'passed'
        result['message'] = f"Selected value: '{action['value']}'"
    
    def _handle_verify_text(self, action: Dict, result: Dict) -> None:
        """Handle text verification"""
        element = WebDriverWait(self.driver, Config.DEFAULT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, action['selector']))
        )
        text = element.text or element.get_attribute("value") or ""
        expected = action.get("expected", "")
        
        if expected in text:
            result['status'] = 'passed'
            result['message'] = f"Text verification passed: '{expected}' found"
        else:
            result['message'] = f"Expected '{expected}', found '{text}'"
    
    def _handle_verify_exists(self, action: Dict, result: Dict) -> None:
        """Handle element existence verification"""
        WebDriverWait(self.driver, Config.DEFAULT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, action['selector']))
        )
        result['status'] = 'passed'
        result['message'] = 'Element exists'
    
    def _handle_verify_visible(self, action: Dict, result: Dict) -> None:
        """Handle visibility verification"""
        element = WebDriverWait(self.driver, Config.DEFAULT_TIMEOUT).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, action['selector']))
        )
        if element.is_displayed():
            result['status'] = 'passed'
            result['message'] = 'Element is visible'
        else:
            result['message'] = "Element exists but is not visible"
    
    def _handle_wait(self, action: Dict, result: Dict) -> None:
        """Handle wait action"""
        duration = action.get('duration', 1000) / 1000
        time.sleep(duration)
        result['status'] = 'passed'
        result['message'] = f'Waited {duration}s'
    
    def _handle_hover(self, action: Dict, result: Dict) -> None:
        """Handle hover/mouse over action"""
        from selenium.webdriver.common.action_chains import ActionChains
        element = WebDriverWait(self.driver, Config.DEFAULT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, action['selector']))
        )
        ActionChains(self.driver).move_to_element(element).perform()
        result['status'] = 'passed'
        result['message'] = 'Hovered over element'
    
    def _handle_scroll_to(self, action: Dict, result: Dict) -> None:
        """Handle scroll to element action"""
        element = WebDriverWait(self.driver, Config.DEFAULT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, action['selector']))
        )
        self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
        result['status'] = 'passed'
        result['message'] = 'Scrolled to element'
    
    def _handle_execute_script(self, action: Dict, result: Dict) -> None:
        """Handle JavaScript execution"""
        script = action.get('script', '')
        script_result = self.driver.execute_script(script)
        result['status'] = 'passed'
        result['message'] = f'Script executed. Result: {script_result}'
    
    def _handle_screenshot(self, action: Dict, result: Dict) -> None:
        """Handle manual screenshot action"""
        screenshot_path = self._capture_screenshot(action, prefix='manual')
        result['status'] = 'passed'
        result['message'] = f'Screenshot captured: {screenshot_path}'
        result['screenshot'] = screenshot_path
    
    def _handle_store_text(self, action: Dict, result: Dict) -> None:
        """Store element text in a variable"""
        element = WebDriverWait(self.driver, Config.DEFAULT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, action['selector']))
        )
        text = element.text or element.get_attribute("value") or ""
        var_name = action.get('variable', 'stored_text')
        self.variables[var_name] = text
        result['status'] = 'passed'
        result['message'] = f"Stored text '{text}' in variable '{var_name}'"
    
    def _handle_verify_url(self, action: Dict, result: Dict) -> None:
        """Verify current URL"""
        current_url = self.driver.current_url
        expected = action.get('expected', '')
        
        if expected in current_url:
            result['status'] = 'passed'
            result['message'] = f"URL verification passed: '{expected}' found in '{current_url}'"
        else:
            result['message'] = f"Expected URL to contain '{expected}', but got '{current_url}'"
    
    def _handle_double_click(self, action: Dict, result: Dict) -> None:
        """Handle double click action"""
        from selenium.webdriver.common.action_chains import ActionChains
        element = WebDriverWait(self.driver, Config.DEFAULT_TIMEOUT).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, action['selector']))
        )
        ActionChains(self.driver).double_click(element).perform()
        result['status'] = 'passed'
        result['message'] = 'Element double-clicked successfully'
    
    def _handle_right_click(self, action: Dict, result: Dict) -> None:
        """Handle right click (context menu) action"""
        from selenium.webdriver.common.action_chains import ActionChains
        element = WebDriverWait(self.driver, Config.DEFAULT_TIMEOUT).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, action['selector']))
        )
        ActionChains(self.driver).context_click(element).perform()
        result['status'] = 'passed'
        result['message'] = 'Element right-clicked successfully'
    
    def _handle_switch_to_frame(self, action: Dict, result: Dict) -> None:
        """Switch to iframe"""
        frame_selector = action.get('selector', '')
        if frame_selector:
            frame = WebDriverWait(self.driver, Config.DEFAULT_TIMEOUT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, frame_selector))
            )
            self.driver.switch_to.frame(frame)
        else:
            self.driver.switch_to.default_content()
        result['status'] = 'passed'
        result['message'] = 'Switched to frame'
    
    def _handle_switch_to_window(self, action: Dict, result: Dict) -> None:
        """Switch to window/tab by index"""
        window_index = action.get('index', -1)
        windows = self.driver.window_handles
        if 0 <= window_index < len(windows):
            self.driver.switch_to.window(windows[window_index])
            result['status'] = 'passed'
            result['message'] = f'Switched to window {window_index}'
        else:
            result['message'] = f'Invalid window index: {window_index}'
    
    def _substitute_variables(self, value: str) -> str:
        """Replace variable placeholders with actual values"""
        if isinstance(value, str):
            for var_name, var_value in self.variables.items():
                value = value.replace(f"${{{var_name}}}", str(var_value))
        return value
    
    def _capture_screenshot(self, action: Dict, prefix: str = 'failure') -> Optional[str]:
        """Capture screenshot on failure or manual request"""
        try:
            timestamp = int(time.time())
            filename = f"{prefix}_{timestamp}_{action.get('type', 'unknown')}.png"
            filepath = Path(Config.SCREENSHOTS_FOLDER) / filename
            self.driver.save_screenshot(str(filepath))
            logger.info(f"Screenshot saved: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"Failed to save screenshot: {e}")
            return None


class TestRunner:
    """Main test execution orchestrator"""
    
    def __init__(self, browser: str = "chrome", headless: bool = False, test_name: str = ""):
        self.browser = browser.lower()
        self.headless = headless
        self.driver = None
        self.test_name = test_name
        self.recording_process = None
    
    def setup_driver(self) -> None:
        """Initialize WebDriver"""
        logger.info(f"Setting up {self.browser} driver (headless={self.headless})")
        
        try:
            if self.browser == "chrome":
                self.driver = BrowserManager.setup_chrome(self.headless)
            elif self.browser == "firefox":
                self.driver = BrowserManager.setup_firefox(self.headless)
            elif self.browser == "edge":
                self.driver = BrowserManager.setup_edge(self.headless)
            else:
                raise ValueError(f"Unsupported browser: {self.browser}")
        except WebDriverException as e:
            logger.error(f"Failed to initialize {self.browser}: {e}")
            raise
    
    def start_recording(self) -> None:
        """Start video recording if enabled (Linux only with ffmpeg)"""
        if not Config.ENABLE_VIDEO_RECORDING or self.headless:
            return
        
        try:
            import subprocess
            timestamp = int(time.time())
            video_path = Path(Config.RECORDINGS_FOLDER) / f"{self.test_name}_{self.browser}_{timestamp}.mp4"
            
            # Check if ffmpeg is available
            result = subprocess.run(['which', 'ffmpeg'], capture_output=True)
            if result.returncode != 0:
                logger.warning("ffmpeg not found. Video recording disabled.")
                return
            
            # Start screen recording (Linux X11)
            self.recording_process = subprocess.Popen([
                'wf-recorder',
                '-f', str(video_path),
                '-r', '30'
            ])

            
            logger.info(f"Recording started: {video_path}")
        except Exception as e:
            logger.warning(f"Could not start recording: {e}")
    
    def stop_recording(self) -> None:
        """Stop video recording"""
        if self.recording_process:
            try:
                self.recording_process.terminate()
                self.recording_process.wait(timeout=5)
                logger.info("Recording stopped")
            except Exception as e:
                logger.error(f"Error stopping recording: {e}")
    
    def cleanup(self) -> None:
        """Clean up WebDriver resources"""
        self.stop_recording()
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")
    
    def run(self, html_path: str, json_path: str) -> Dict[str, Any]:
        """Execute complete test suite"""
        try:
            self.setup_driver()
            self.start_recording()
            
            # Load HTML file
            file_url = f"file://{Path(html_path).resolve()}"
            logger.info(f"Loading URL: {file_url}")
            self.driver.get(file_url)
            time.sleep(1)
            
            # Load test actions
            with open(json_path, 'r', encoding='utf-8') as f:
                actions = json.load(f)
            
            # Update test status
            with test_lock:
                if self.test_name in active_tests:
                    active_tests[self.test_name].total = len(actions)
            
            # Execute actions
            executor = ActionExecutor(self.driver)
            results = []
            passed = failed = 0
            
            for idx, action in enumerate(actions, 1):
                logger.info(f"Executing action {idx}/{len(actions)}: {action.get('type')}")
                start_time = time.time()
                
                result = executor.execute(action)
                result['duration'] = round(time.time() - start_time, 3)
                results.append(result)
                
                if result['status'] == 'passed':
                    passed += 1
                else:
                    failed += 1
                
                # Update progress
                with test_lock:
                    if self.test_name in active_tests:
                        active_tests[self.test_name].progress = idx
                
                time.sleep(Config.ACTION_DELAY)
            
            # Build summary
            total = len(actions)
            summary = {
                'browser': self.browser,
                'total': total,
                'passed': passed,
                'failed': failed,
                'success_rate': round((passed / total) * 100, 2) if total else 0,
                'duration': sum(r.get('duration', 0) for r in results)
            }
            
            logger.info(f"Test completed - Passed: {passed}, Failed: {failed}")
            
            return {
                'summary': summary,
                'details': results,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
        except Exception as e:
            logger.error(f"Error running tests: {e}")
            raise
        finally:
            self.cleanup()


class TestManager:
    """Manages test file operations"""
    
    @staticmethod
    def sanitize_name(name: str) -> str:
        """Sanitize test name for filesystem"""
        return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip()
    
    @staticmethod
    def get_test_dir(test_name: str) -> Path:
        """Get test directory path"""
        return Path(Config.UPLOAD_FOLDER) / test_name
    
    @staticmethod
    def save_test_files(test_name: str, html_file, json_file) -> bool:
        """Save uploaded test files"""
        test_dir = TestManager.get_test_dir(test_name)
        test_dir.mkdir(exist_ok=True)
        
        html_path = test_dir / 'test.html'
        json_path = test_dir / 'actions.json'
        
        html_file.save(str(html_path))
        json_file.save(str(json_path))
        
        # Validate JSON
        try:
            with open(json_path, 'r') as f:
                json.load(f)
            return True
        except json.JSONDecodeError:
            shutil.rmtree(test_dir)
            return False
    
    @staticmethod
    def list_tests() -> List[str]:
        """List all available tests"""
        upload_dir = Path(Config.UPLOAD_FOLDER)
        return sorted([d.name for d in upload_dir.iterdir() if d.is_dir()])
    
    @staticmethod
    def delete_test(test_name: str) -> bool:
        """Delete a test"""
        test_dir = TestManager.get_test_dir(test_name)
        if test_dir.exists():
            shutil.rmtree(test_dir)
            return True
        return False
    
    @staticmethod
    def save_report(test_name: str, results: Dict) -> str:
        """Save test report"""
        report_path = Path(Config.REPORTS_FOLDER) / f'{test_name}_report.json'
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        logger.info(f"Report saved: {report_path}")
        return str(report_path)
    
    @staticmethod
    def get_test_history(test_name: str) -> List[Dict]:
        """Get execution history for a test"""
        report_path = Path(Config.REPORTS_FOLDER) / f'{test_name}_report.json'
        if report_path.exists():
            with open(report_path, 'r') as f:
                return json.load(f)
        return []
    
    @staticmethod
    def export_to_html(test_name: str, results: Dict) -> str:
        """Export test results to HTML report"""
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Test Report: {test_name}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .summary {{ background: #f0f0f0; padding: 15px; border-radius: 5px; }}
                .passed {{ color: green; }}
                .failed {{ color: red; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #4CAF50; color: white; }}
                img {{ max-width: 300px; cursor: pointer; }}
            </style>
        </head>
        <body>
            <h1>Test Report: {test_name}</h1>
            <div class="summary">
                <h2>Summary</h2>
                <p><strong>Browser:</strong> {results.get('summary', {}).get('browser', 'N/A')}</p>
                <p><strong>Total Tests:</strong> {results.get('summary', {}).get('total', 0)}</p>
                <p><strong>Passed:</strong> <span class="passed">{results.get('summary', {}).get('passed', 0)}</span></p>
                <p><strong>Failed:</strong> <span class="failed">{results.get('summary', {}).get('failed', 0)}</span></p>
                <p><strong>Success Rate:</strong> {results.get('summary', {}).get('success_rate', 0)}%</p>
                <p><strong>Timestamp:</strong> {results.get('timestamp', 'N/A')}</p>
            </div>
            
            <h2>Test Details</h2>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Action</th>
                        <th>Selector</th>
                        <th>Status</th>
                        <th>Message</th>
                        <th>Duration</th>
                        <th>Screenshot</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for idx, detail in enumerate(results.get('details', []), 1):
            status_class = 'passed' if detail['status'] == 'passed' else 'failed'
            screenshot = f"<img src='{detail['screenshot']}' alt='Screenshot'/>" if detail.get('screenshot') else 'N/A'
            
            html_content += f"""
                    <tr>
                        <td>{idx}</td>
                        <td>{detail['action']}</td>
                        <td>{detail.get('selector', 'N/A')}</td>
                        <td class="{status_class}">{detail['status'].upper()}</td>
                        <td>{detail['message']}</td>
                        <td>{detail.get('duration', 0)}s</td>
                        <td>{screenshot}</td>
                    </tr>
            """
        
        html_content += """
                </tbody>
            </table>
        </body>
        </html>
        """
        
        report_path = Path(Config.REPORTS_FOLDER) / f'{test_name}_report.html'
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return str(report_path)


# ==================== FLASK ROUTES ====================

@app.route('/')
def index():
    """Main page"""
    return render_template('home.html')


@app.route('/upload', methods=['POST'])
def upload_files():
    """Upload HTML and JSON test files"""
    try:
        test_name = request.form.get('test_name', '').strip()
        if not test_name:
            return jsonify({'success': False, 'message': 'Test name required'})
        
        test_name = TestManager.sanitize_name(test_name)
        if not test_name:
            return jsonify({'success': False, 'message': 'Invalid test name'})
        
        html_file = request.files.get('html_file')
        json_file = request.files.get('json_file')
        
        if not html_file or not json_file:
            return jsonify({'success': False, 'message': 'Both files required'})
        
        if TestManager.save_test_files(test_name, html_file, json_file):
            logger.info(f"Test '{test_name}' uploaded successfully")
            return jsonify({'success': True, 'message': 'Files uploaded successfully'})
        else:
            return jsonify({'success': False, 'message': 'Invalid JSON format'})
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/list_tests')
def list_tests():
    """List all available tests"""
    try:
        tests = TestManager.list_tests()
        return jsonify({'tests': tests})
    except Exception as e:
        logger.error(f"List error: {e}")
        return jsonify({'tests': [], 'error': str(e)})


@app.route('/run_test', methods=['POST'])
def run_test():
    """Execute test suite"""
    try:
        data = request.json
        test_name = data.get('test_name')
        browser = data.get('browser', 'chrome')
        headless = data.get('headless', False)
        parallel = data.get('parallel', False)
        
        if not test_name:
            return jsonify({'error': 'Test name required'})
        
        test_dir = TestManager.get_test_dir(test_name)
        html_path = test_dir / 'test.html'
        json_path = test_dir / 'actions.json'
        
        if not html_path.exists() or not json_path.exists():
            return jsonify({'error': 'Test files not found'})
        
        # Initialize test status
        with test_lock:
            active_tests[test_name] = TestStatus(
                test_name=test_name,
                status='running',
                progress=0,
                total=0,
                start_time=time.time(),
                browser=browser
            )
        
        # Run tests
        if browser == "all":
            browsers = ["chrome", "firefox", "edge"]
            
            if parallel and Config.PARALLEL_EXECUTION:
                # Parallel execution
                results = []
                with ThreadPoolExecutor(max_workers=min(len(browsers), Config.MAX_PARALLEL_TESTS)) as executor:
                    future_to_browser = {
                        executor.submit(
                            TestRunner(b, headless, test_name).run,
                            str(html_path),
                            str(json_path)
                        ): b for b in browsers
                    }
                    
                    for future in as_completed(future_to_browser):
                        b = future_to_browser[future]
                        try:
                            result = future.result()
                            results.append(result)
                        except Exception as e:
                            logger.error(f"Error on {b}: {e}")
                            results.append({
                                'summary': {
                                    'browser': b,
                                    'total': 0,
                                    'passed': 0,
                                    'failed': 0,
                                    'success_rate': 0
                                },
                                'details': [],
                                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                'error': str(e)
                            })
            else:
                # Sequential execution
                results = []
                for b in browsers:
                    try:
                        logger.info(f"Running test '{test_name}' on {b}")
                        runner = TestRunner(browser=b, headless=headless, test_name=test_name)
                        result = runner.run(str(html_path), str(json_path))
                        results.append(result)
                    except Exception as e:
                        logger.error(f"Error on {b}: {e}")
                        results.append({
                            'summary': {
                                'browser': b,
                                'total': 0,
                                'passed': 0,
                                'failed': 0,
                                'success_rate': 0
                            },
                            'details': [],
                            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            'error': str(e)
                        })
        else:
            logger.info(f"Running test '{test_name}' on {browser}")
            runner = TestRunner(browser=browser, headless=headless, test_name=test_name)
            results = runner.run(str(html_path), str(json_path))
        
        # Update test status
        with test_lock:
            if test_name in active_tests:
                active_tests[test_name].status = 'completed'
        
        # Save reports
        TestManager.save_report(test_name, results)
        TestManager.export_to_html(test_name, results)
        
        return jsonify(results)
        
    except Exception as e:
        logger.error(f"Test execution error: {e}")
        with test_lock:
            if test_name in active_tests:
                active_tests[test_name].status = 'failed'
        return jsonify({'error': str(e)})


@app.route('/test_status/<test_name>')
def test_status(test_name):
    """Get current test execution status"""
    with test_lock:
        if test_name in active_tests:
            status = active_tests[test_name]
            elapsed = time.time() - status.start_time
            return jsonify({
                **status.to_dict(),
                'elapsed_time': round(elapsed, 2)
            })
        else:
            return jsonify({'error': 'Test not found'}), 404


@app.route('/compare_tests', methods=['POST'])
def compare_tests():
    """Compare results from multiple test runs"""
    try:
        test_names = request.json.get('test_names', [])
        
        if not test_names:
            return jsonify({'error': 'Test names required'})
        
        comparison = []
        for test_name in test_names:
            history = TestManager.get_test_history(test_name)
            if history:
                comparison.append({
                    'test_name': test_name,
                    'history': history
                })
        
        return jsonify({'comparison': comparison})
        
    except Exception as e:
        logger.error(f"Comparison error: {e}")
        return jsonify({'error': str(e)})


@app.route('/download_html_report/<test_name>')
def download_html_report(test_name):
    """Download HTML report"""
    try:
        report_path = Path(Config.REPORTS_FOLDER) / f'{test_name}_report.html'
        if report_path.exists():
            return send_file(str(report_path), as_attachment=True)
        else:
            return jsonify({'error': 'HTML report not found'}), 404
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/retry_failed', methods=['POST'])
def retry_failed():
    """Retry only failed test actions"""
    try:
        data = request.json
        test_name = data.get('test_name')
        
        if not test_name:
            return jsonify({'error': 'Test name required'})
        
        # Get previous test results
        history = TestManager.get_test_history(test_name)
        if not history:
            return jsonify({'error': 'No test history found'})
        
        # Extract failed actions
        if isinstance(history, list):
            last_run = history[-1] if history else {}
        else:
            last_run = history
        
        failed_actions = [
            detail for detail in last_run.get('details', [])
            if detail['status'] == 'failed'
        ]
        
        if not failed_actions:
            return jsonify({'message': 'No failed actions to retry'})
        
        # Create temporary JSON with only failed actions
        test_dir = TestManager.get_test_dir(test_name)
        retry_json_path = test_dir / 'retry_actions.json'
        
        with open(retry_json_path, 'w') as f:
            json.dump(failed_actions, f, indent=2)
        
        # Run retry test
        browser = data.get('browser', 'chrome')
        headless = data.get('headless', False)
        html_path = test_dir / 'test.html'
        
        runner = TestRunner(browser=browser, headless=headless, test_name=f"{test_name}_retry")
        results = runner.run(str(html_path), str(retry_json_path))
        
        # Clean up temporary file
        retry_json_path.unlink()
        
        return jsonify(results)
        
    except Exception as e:
        logger.error(f"Retry error: {e}")
        return jsonify({'error': str(e)})


@app.route('/delete_test', methods=['POST'])
def delete_test():
    """Delete test suite"""
    try:
        test_name = request.json.get('test_name')
        if not test_name:
            return jsonify({'success': False, 'message': 'Test name required'})
        
        if TestManager.delete_test(test_name):
            logger.info(f"Test '{test_name}' deleted")
            return jsonify({'success': True, 'message': 'Test deleted successfully'})
        else:
            return jsonify({'success': False, 'message': 'Test not found'})
        
    except Exception as e:
        logger.error(f"Delete error: {e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/download_report/<test_name>')
def download_report(test_name):
    """Download test report"""
    try:
        report_path = Path(Config.REPORTS_FOLDER) / f'{test_name}_report.json'
        if report_path.exists():
            return send_file(str(report_path), as_attachment=True)
        else:
            return jsonify({'error': 'Report not found'}), 404
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({'error': str(e)}), 500


@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle oversized file uploads"""
    return jsonify({'error': 'File too large. Max size: 16MB'}), 413


if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')