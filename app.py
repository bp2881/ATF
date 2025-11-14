"""
Flask Automated HTML Testing Application
Install dependencies: pip install flask selenium beautifulsoup4
"""

from flask import Flask, render_template, request, jsonify, send_file
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import WebDriverException
import json
import os
import time
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'test_files'
app.config['REPORTS_FOLDER'] = 'test_reports'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create necessary folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['REPORTS_FOLDER'], exist_ok=True)
os.makedirs("screenshots", exist_ok=True)


class TestRunner:
    def __init__(self):
        self.driver = None

    def setup_driver(self, browser="chrome", headless=False):
        """Initialize WebDriver for specified browser"""
        
        # Custom driver paths for Windows
        CUSTOM_GECKO = r"C:\\Drivers\\Firefox\\geckodriver.exe"       
        CUSTOM_EDGE  = r"C:\\Drivers\\Edge\\msedgedriver.exe"      

        logger.info(f"Setting up {browser} driver (headless={headless})")
        browser = browser.lower()

        try:
            if browser == "chrome":
                from selenium.webdriver.chrome.options import Options
                
                options = Options()
                if headless:
                    options.add_argument("--headless=new")
                options.add_argument("--disable-gpu")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--window-size=1920,1080")
                
                return webdriver.Chrome(options=options)

            elif browser == "firefox":
                from selenium.webdriver.firefox.options import Options as FFOptions
                from selenium.webdriver.firefox.service import Service as FFService

                options = FFOptions()
                if headless:
                    options.add_argument("--headless")
                options.add_argument("--width=1920")
                options.add_argument("--height=1080")

                if os.name == "nt" and os.path.exists(CUSTOM_GECKO):
                    service = FFService(executable_path=CUSTOM_GECKO)
                else:
                    service = FFService()

                return webdriver.Firefox(service=service, options=options)

            elif browser == "edge":
                from selenium.webdriver.edge.options import Options
                from selenium.webdriver.edge.service import Service

                options = Options()
                if headless:
                    options.add_argument("--headless=new")
                options.add_argument("--disable-gpu")
                options.add_argument("--window-size=1920,1080")

                if os.name == "nt" and os.path.exists(CUSTOM_EDGE):
                    service = Service(executable_path=CUSTOM_EDGE)
                else:
                    service = Service()

                return webdriver.Edge(service=service, options=options)

            else:
                raise ValueError(f"Unsupported browser: {browser}")
                
        except WebDriverException as e:
            logger.error(f"Failed to initialize {browser} driver: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error setting up {browser}: {str(e)}")
            raise

    def cleanup(self):
        """Close and quit the WebDriver"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.error(f"Error during cleanup: {str(e)}")

    def execute_action(self, action):
        """Execute a single test action"""
        result = {
            'action': action['type'],
            'selector': action.get('selector', ''),
            'status': 'failed',
            'message': '',
            'timestamp': datetime.now().isoformat()
        }

        try:
            action_type = action['type']

            if action_type == 'click':
                element = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, action['selector']))
                )
                element.click()
                result['status'] = 'passed'
                result['message'] = 'Element clicked successfully'

            elif action_type == 'input':
                element = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, action['selector']))
                )
                element.clear()
                element.send_keys(action['value'])
                result['status'] = 'passed'
                result['message'] = f"Input value: '{action['value']}'"

            elif action_type == 'select':
                element = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, action['selector']))
                )
                Select(element).select_by_value(action['value'])
                result['status'] = 'passed'
                result['message'] = f"Selected value: '{action['value']}'"

            elif action_type == 'verify_text':
                element = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, action['selector']))
                )
                text = element.text or element.get_attribute("value") or ""
                expected = action.get("expected", "")
                
                if expected in text:
                    result['status'] = 'passed'
                    result['message'] = f"Text verification passed: '{expected}' found"
                else:
                    result['message'] = f"Expected '{expected}', but found '{text}'"

            elif action_type == 'verify_exists':
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, action['selector']))
                )
                result['status'] = 'passed'
                result['message'] = 'Element exists'

            elif action_type == 'verify_visible':
                element = WebDriverWait(self.driver, 10).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, action['selector']))
                )
                if element.is_displayed():
                    result['status'] = 'passed'
                    result['message'] = 'Element is visible'
                else:
                    result['message'] = "Element exists but is not visible"

            elif action_type == 'wait':
                duration = action.get('duration', 1000) / 1000
                time.sleep(duration)
                result['status'] = 'passed'
                result['message'] = f'Waited {duration}s'

            else:
                result['message'] = f"Unknown action type: {action_type}"

        except Exception as e:
            # Capture screenshot on failure
            screenshot_name = f"{int(time.time())}_{action.get('type', 'unknown')}.png"
            screenshot_path = os.path.join("screenshots", screenshot_name)
            
            try:
                self.driver.save_screenshot(screenshot_path)
                result['screenshot'] = screenshot_path
                logger.info(f"Screenshot saved: {screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"Failed to save screenshot: {str(screenshot_error)}")
                result['screenshot'] = None

            result['message'] = str(e)
            logger.error(f"Action failed - {action_type}: {str(e)}")

        return result

    def run_tests(self, html_path, json_path, browser="chrome", headless=False):
        """Run complete test suite"""
        
        try:
            # Setup driver
            self.driver = self.setup_driver(browser=browser, headless=headless)
            
            # Load HTML file
            file_url = f"file://{os.path.abspath(html_path)}"
            logger.info(f"Loading URL: {file_url}")
            self.driver.get(file_url)
            
            # Wait for page to load
            time.sleep(1)

            # Load test actions
            with open(json_path, 'r', encoding='utf-8') as f:
                actions = json.load(f)

            results = []
            passed = 0
            failed = 0

            # Execute each action
            for idx, action in enumerate(actions, 1):
                logger.info(f"Executing action {idx}/{len(actions)}: {action.get('type')}")
                start_time = time.time()
                
                result = self.execute_action(action)
                result['duration'] = round(time.time() - start_time, 3)
                results.append(result)

                if result['status'] == 'passed':
                    passed += 1
                else:
                    failed += 1
                    
                # Small delay between actions
                time.sleep(0.5)

            # Prepare summary
            summary = {
                'browser': browser,
                'total': len(actions),
                'passed': passed,
                'failed': failed,
                'success_rate': round((passed / len(actions)) * 100, 2) if actions else 0
            }

            logger.info(f"Test completed - Passed: {passed}, Failed: {failed}")

            return {
                'summary': summary,
                'details': results,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        except Exception as e:
            logger.error(f"Error running tests: {str(e)}")
            raise
        finally:
            self.cleanup()


# ---------------------- FLASK ROUTES ---------------------------

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
            return jsonify({'success': False, 'message': 'Test name is required'})
        
        # Sanitize test name
        test_name = "".join(c for c in test_name if c.isalnum() or c in (' ', '_', '-')).strip()
        
        if not test_name:
            return jsonify({'success': False, 'message': 'Invalid test name'})
            
        html_file = request.files.get('html_file')
        json_file = request.files.get('json_file')

        if not html_file or not json_file:
            return jsonify({'success': False, 'message': 'Both HTML and JSON files are required'})

        # Create test directory
        test_dir = os.path.join(app.config['UPLOAD_FOLDER'], test_name)
        os.makedirs(test_dir, exist_ok=True)

        # Save files
        html_path = os.path.join(test_dir, 'test.html')
        json_path = os.path.join(test_dir, 'actions.json')

        html_file.save(html_path)
        json_file.save(json_path)
        
        # Validate JSON file
        try:
            with open(json_path, 'r') as f:
                json.load(f)
        except json.JSONDecodeError:
            # Clean up if JSON is invalid
            import shutil
            shutil.rmtree(test_dir)
            return jsonify({'success': False, 'message': 'Invalid JSON file format'})

        logger.info(f"Test '{test_name}' uploaded successfully")
        return jsonify({'success': True, 'message': 'Files uploaded successfully'})
        
    except Exception as e:
        logger.error(f"Error uploading files: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/list_tests')
def list_tests():
    """List all uploaded tests"""
    try:
        tests = [d for d in os.listdir(app.config['UPLOAD_FOLDER'])
                 if os.path.isdir(os.path.join(app.config['UPLOAD_FOLDER'], d))]
        tests.sort()
        return jsonify({'tests': tests})
    except Exception as e:
        logger.error(f"Error listing tests: {str(e)}")
        return jsonify({'tests': [], 'error': str(e)})


@app.route('/run_test', methods=['POST'])
def run_test():
    """Execute a test suite"""
    try:
        data = request.json
        test_name = data.get('test_name')
        browser = data.get('browser', 'chrome')
        headless = data.get('headless', False)

        if not test_name:
            return jsonify({'error': 'Test name is required'})

        test_dir = os.path.join(app.config['UPLOAD_FOLDER'], test_name)
        html_path = os.path.join(test_dir, 'test.html')
        json_path = os.path.join(test_dir, 'actions.json')

        if not os.path.exists(html_path) or not os.path.exists(json_path):
            return jsonify({'error': 'Test files not found'})

        # Run tests
        if browser == "all":
            # Run on all browsers
            all_results = []
            browsers = ["chrome", "firefox", "edge"]
            
            for b in browsers:
                try:
                    logger.info(f"Running test '{test_name}' on {b}")
                    runner = TestRunner()
                    result = runner.run_tests(html_path, json_path, browser=b, headless=headless)
                    all_results.append(result)
                except Exception as e:
                    logger.error(f"Error running test on {b}: {str(e)}")
                    all_results.append({
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
            
            results = all_results
        else:
            # Run on single browser
            logger.info(f"Running test '{test_name}' on {browser}")
            runner = TestRunner()
            results = runner.run_tests(html_path, json_path, browser=browser, headless=headless)

        # Save report
        report_path = os.path.join(app.config['REPORTS_FOLDER'], f'{test_name}_report.json')
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)

        logger.info(f"Test report saved: {report_path}")
        return jsonify(results)

    except Exception as e:
        logger.error(f"Error running test: {str(e)}")
        return jsonify({'error': str(e)})


@app.route('/delete_test', methods=['POST'])
def delete_test():
    """Delete a test suite"""
    try:
        import shutil
        test_name = request.json.get('test_name')
        
        if not test_name:
            return jsonify({'success': False, 'message': 'Test name is required'})
            
        test_dir = os.path.join(app.config['UPLOAD_FOLDER'], test_name)

        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
            logger.info(f"Test '{test_name}' deleted")
            return jsonify({'success': True, 'message': 'Test deleted successfully'})
        else:
            return jsonify({'success': False, 'message': 'Test not found'})
            
    except Exception as e:
        logger.error(f"Error deleting test: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/download_report/<test_name>')
def download_report(test_name):
    """Download test report"""
    try:
        report_path = os.path.join(app.config['REPORTS_FOLDER'], f'{test_name}_report.json')

        if os.path.exists(report_path):
            return send_file(report_path, as_attachment=True)
        else:
            return jsonify({'error': 'Report not found'}), 404
            
    except Exception as e:
        logger.error(f"Error downloading report: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file too large error"""
    return jsonify({'error': 'File too large. Maximum size is 16MB'}), 413


if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')