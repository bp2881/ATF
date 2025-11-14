function loadFiles() {
	fetch("/list_tests")
		.then((response) => response.json())
		.then((data) => {
			const filesList = document.getElementById("filesList");
			if (data.tests.length === 0) {
				filesList.innerHTML =
					'<div class="empty-state" style="grid-column: 1/-1;"><div class="empty-state-icon">📭</div><p class="empty-state-text">No tests saved yet</p></div>';
				return;
			}
			filesList.innerHTML = data.tests
				.map(
					(test) => `
                <div class="file-item">
                    <div class="file-name">${test}</div>
                    <div class="file-actions">
                        <button class="btn btn-small" onclick="runTest('${test}')">Run Test</button>
                        <button class="btn btn-small btn-secondary" onclick="deleteTest('${test}')">Delete</button>
                    </div>
                </div>
            `
				)
				.join("");
		});
}

function updateFileName(input, labelId) {
	const label = document.getElementById(labelId);
	const textSpan = label.querySelector(".file-upload-text span:last-child");
	if (input.files.length > 0) {
		textSpan.textContent = input.files[0].name;
		textSpan.classList.add("file-selected");
	} else {
		const fileType = labelId.includes("html") ? "HTML" : "JSON";
		textSpan.textContent = `Choose ${fileType} file`;
		textSpan.classList.remove("file-selected");
	}
}

function uploadFiles() {
	const testName = document.getElementById("testName").value;
	const htmlFile = document.getElementById("htmlFile").files[0];
	const jsonFile = document.getElementById("jsonFile").files[0];

	if (!testName || !htmlFile || !jsonFile) {
		alert("Please provide test name and both files");
		return;
	}

	const formData = new FormData();
	formData.append("test_name", testName);
	formData.append("html_file", htmlFile);
	formData.append("json_file", jsonFile);
	formData.append("browser", document.getElementById("browser").value);
	formData.append("headless", document.getElementById("headless").checked);

	fetch("/upload", {
		method: "POST",
		body: formData,
	})
		.then((response) => response.json())
		.then((data) => {
			if (data.success) {
				alert("Files uploaded successfully!");
				document.getElementById("testName").value = "";
				document.getElementById("htmlFile").value = "";
				document.getElementById("jsonFile").value = "";
				updateFileName(
					document.getElementById("htmlFile"),
					"htmlLabel"
				);
				updateFileName(
					document.getElementById("jsonFile"),
					"jsonLabel"
				);
				loadFiles();
			} else {
				alert("Error: " + data.message);
			}
		});
}

function runTest(testName) {
	const resultsDiv = document.getElementById("testResults");
	resultsDiv.innerHTML =
		'<div class="card loading"><div class="spinner"></div><p>Running tests...</p></div>';

	const browser = document.getElementById("browser").value;
	const headless = document.getElementById("headless").checked;

	fetch("/run_test", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			test_name: testName,
			browser: browser,
			headless: headless,
		}),
	})
		.then((response) => response.json())
		.then((data) => {
			if (data.error) {
				resultsDiv.innerHTML = `<div class="card"><h2 style="color: #f87171;">Error</h2><p style="color: #d4d4d8; margin-top: 12px;">${data.error}</p></div>`;
				return;
			}

			// support both single-result and array-of-results (for "all" browsers)
			const resultsArray = Array.isArray(data) ? data : [data];

			let output = "";
			for (const res of resultsArray) {
				const summary = res.summary || {};
				const details = res.details || [];

				output += `
            <div class="card">
                <div class="result-header">
                    <h2>📊 Test Results: ${testName} ${
					summary.browser ? "- " + summary.browser : ""
				}</h2>
                    <button class="btn btn-small" onclick="downloadReport('${testName}')" style="width: auto; padding: 12px 24px;">Download Report</button>
                </div>
                
                <div class="stats">
                    <div class="stat-box total">
                        <div class="stat-number">${summary.total ?? 0}</div>
                        <div class="stat-label">Total Tests</div>
                    </div>
                    <div class="stat-box passed">
                        <div class="stat-number">${summary.passed ?? 0}</div>
                        <div class="stat-label">Passed</div>
                    </div>
                    <div class="stat-box failed">
                        <div class="stat-number">${summary.failed ?? 0}</div>
                        <div class="stat-label">Failed</div>
                    </div>
                    <div class="stat-box rate">
                        <div class="stat-number">${
							summary.success_rate ?? 0
						}%</div>
                        <div class="stat-label">Success Rate</div>
                    </div>
                </div>

                <div class="details-section">
                    <h3 class="details-header">Test Details</h3>
                    ${details
						.map(
							(detail) => `
                        <div class="test-detail ${detail.status}">
                            <strong>
                                <span class="status-icon">${
									detail.status === "passed" ? "✓" : "✗"
								}</span>
                                <span>${detail.action}</span>
                            </strong>
                            ${
								detail.selector
									? `<div class="action-code">${detail.selector}</div>`
									: ""
							}
                            <div class="test-message">${detail.message}${
								detail.screenshot
									? `<div style="margin-top:10px;"><a href="${detail.screenshot}" target="_blank">View screenshot</a></div>`
									: ""
							}</div>
                        </div>
                    `
						)
						.join("")}
                </div>

                <p class="result-timestamp">
                    Report generated at: ${res.timestamp || ""}
                </p>
            </div>
            `;
			}

			resultsDiv.innerHTML = output;
		})
		.catch((err) => {
			resultsDiv.innerHTML = `<div class="card"><h2 style="color: #f87171;">Error</h2><pre style="color:#d4d4d8">${err}</pre></div>`;
		});
}

function deleteTest(testName) {
	if (!confirm(`Are you sure you want to delete "${testName}"?`)) {
		return;
	}

	fetch("/delete_test", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ test_name: testName }),
	})
		.then((response) => response.json())
		.then((data) => {
			if (data.success) {
				alert("Test deleted successfully!");
				loadFiles();
			} else {
				alert("Error: " + data.message);
			}
		});
}

function downloadReport(testName) {
	window.location.href = `/download_report/${testName}`;
}

loadFiles();
