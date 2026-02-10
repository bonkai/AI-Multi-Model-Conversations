document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Elements ---
    const storySelect = document.getElementById('story-select');
    const loadStoryButton = document.getElementById('load-story-button');
    const storyContentDiv = document.getElementById('story-content');
    const storyTitleElement = document.getElementById('story-title');
    const storyTextElement = document.getElementById('story-text');
    const choicesContainerElement = document.getElementById('choices-container');
    const errorMessageElement = document.getElementById('error-message');

    // --- State Variables ---
    let storyData = null; // To hold the loaded story JSON object
    let currentNodeId = null; // To track the current position in the story

    // --- Functions ---

    // Function to display errors
    function displayError(message) {
        errorMessageElement.textContent = message;
        errorMessageElement.classList.remove('hidden');
        storyContentDiv.classList.add('hidden'); // Hide story content on error
        console.error(message);
    }

    // Function to clear errors
    function clearError() {
        errorMessageElement.textContent = '';
        errorMessageElement.classList.add('hidden');
    }

    // Function to render the current node
    function renderNode() {
        clearError();
        if (!storyData || !currentNodeId || !storyData.nodes[currentNodeId]) {
            displayError(`Error: Could not find node data for ID: ${currentNodeId}`);
            return;
        }

        const node = storyData.nodes[currentNodeId];

        // Display story text
        // Use innerHTML carefully if your text might contain HTML, otherwise textContent is safer
        storyTextElement.innerHTML = node.text.replace(/\n/g, '<br>'); // Replace newlines with <br>

        // Clear previous choices
        choicesContainerElement.innerHTML = '';

        // Display choices as buttons
        if (node.isEnding) {
            const endMessage = document.createElement('p');
            endMessage.textContent = "-- THE END --";
            endMessage.style.fontWeight = 'bold';
            endMessage.style.textAlign = 'center';
            choicesContainerElement.appendChild(endMessage);
        } else if (node.choices && node.choices.length > 0) {
            node.choices.forEach(choice => {
                const button = document.createElement('button');
                button.textContent = choice.text;
                // Store the next node ID in a data attribute
                button.dataset.nextNodeId = choice.nextNodeId;
                button.addEventListener('click', handleChoiceClick);
                choicesContainerElement.appendChild(button);
            });
        } else {
            // Node is not an ending but has no choices - might be an error in JSON generation
            const warning = document.createElement('p');
            warning.textContent = "[No choices available, but not marked as an ending.]";
            warning.style.fontStyle = 'italic';
            choicesContainerElement.appendChild(warning);
        }
    }

    // Function to handle choice button clicks
    function handleChoiceClick(event) {
        const nextNodeId = event.target.dataset.nextNodeId;
        if (nextNodeId && storyData.nodes[nextNodeId]) {
            currentNodeId = nextNodeId;
            renderNode();
        } else if (nextNodeId) {
            displayError(`Error: The choice leads to an invalid or missing node ID: ${nextNodeId}`);
        } else {
             displayError("Error: Choice button is missing the target node ID.");
        }
    }

    // Function to load the selected story data
    async function loadStoryData() {
        const selectedFilename = storySelect.value;
        if (!selectedFilename) {
            displayError("Please select a story to load.");
            return;
        }

        clearError();
        storyContentDiv.classList.add('hidden'); // Hide while loading
        const filePath = `./stories/${selectedFilename}`; // Assuming stories are in 'stories' subdirectory

        try {
            const response = await fetch(filePath);
            if (!response.ok) {
                // Handle HTTP errors like 404 Not Found
                throw new Error(`Failed to load story file '${selectedFilename}'. Status: ${response.status} ${response.statusText}`);
            }
            storyData = await response.json(); // Parse the JSON data

            // Basic validation of loaded data
            if (!storyData.startNodeId || !storyData.nodes || typeof storyData.nodes !== 'object') {
                throw new Error("Invalid story file format: Missing 'startNodeId' or 'nodes' structure.");
            }
            if (!storyData.nodes[storyData.startNodeId]) {
                 throw new Error(`Invalid story file: Start node ID '${storyData.startNodeId}' does not exist in nodes.`);
            }


            // Set up the story
            currentNodeId = storyData.startNodeId;
            storyTitleElement.textContent = selectedFilename.replace('.json', '').replace(/_/g, ' '); // Basic title
            storyContentDiv.classList.remove('hidden'); // Show story area
            renderNode(); // Render the starting node

        } catch (error) {
            storyData = null; // Reset story data on error
            currentNodeId = null;
            displayError(`Error loading or parsing story: ${error.message}`);
        }
    }

     // Function to populate the story selection dropdown
     async function loadStoryList() {
        try {
            const response = await fetch('./stories.json'); // Fetch the list of filenames
            if (!response.ok) {
                throw new Error(`Failed to load story list (stories.json). Status: ${response.status}`);
            }
            const storyFiles = await response.json();

            if (!Array.isArray(storyFiles)) {
                 throw new Error("Invalid format for stories.json: Should be an array of filenames.");
            }

            // Clear existing options except the placeholder
            storySelect.innerHTML = '<option value="">--Please choose a story--</option>';

            // Add each story file as an option
            storyFiles.forEach(filename => {
                if (typeof filename === 'string' && filename.endsWith('.json')) {
                    const option = document.createElement('option');
                    option.value = filename;
                    // Make the display text more readable
                    option.textContent = filename.replace('.json', '').replace(/_/g, ' ').replace(/-/g, ' ');
                    storySelect.appendChild(option);
                } else {
                     console.warn(`Skipping invalid entry in stories.json: ${filename}`);
                }
            });

        } catch (error) {
             // Display error within the selector area if list fails to load
             storySelect.innerHTML = '<option value="">Error loading stories</option>';
             console.error(`Error loading story list: ${error.message}`);
             // Optionally display a more prominent error message
             displayError(`Could not load the list of available stories from stories.json. ${error.message}`);
        }
    }


    // --- Event Listeners ---
    loadStoryButton.addEventListener('click', loadStoryData);

    // --- Initial Load ---
    loadStoryList(); // Populate the dropdown when the page loads

}); // End DOMContentLoaded
