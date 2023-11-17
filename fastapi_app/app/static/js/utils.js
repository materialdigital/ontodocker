/* Utils include resize window, toggle sidebar, go back to top, flash message, toast message,
Yasgui tab switch, copy to clipboard, modal message for future function, tooltip, etc.
 */


/* Future feature modal */
function future(event) {
    event.preventDefault();
    $("#exampleModal .modal-header").text('Coming Soon');
    $("#exampleModal .modal-body").text('This feature will be available soon.');
    $('#exampleModal').modal('toggle');
}
/* end of Future feature modal */


/* Copy to clipboard
Note: The use of navigator.clipboard requires a secure origin.
So if your dev environment is being served over HTTP, then the navigator.clipboard.writeText() method won't be available.
*/
function CopyToClipboard(id) {
    let copyText = document.getElementById(id);
    copyText.select();
    copyText.setSelectionRange(0, 99999); //For mobile devices

    if (navigator.clipboard) {
        navigator.clipboard.writeText(copyText.value);
    } else {
        $('#exampleModal .modal-header').text('Copy');
        $('#exampleModal .modal-body').text('The copy function is disabled for HTTP connections.');
        $('#exampleModal').modal('toggle');
        // document.execCommand('copy'); // deprecated but work over HTTP (not recommended)
    }
}
/* end of Copy to clipboard*/


/* Flash message */
function showFlashMessage(type, message, message_type) {
    const flashMessage = $("<div>", {
        class: `alert alert-${type} mb-0`, // .mb-0 to remove bottom margin
        role: "alert",
    });
    if (message_type === "html") {
        flashMessage.html(message);
    } else if (message_type === "text") {
        flashMessage.text(message);
    }

    // Empty the existing content of the flash message container
    $("#flash-message-axios").empty();
    // Append the flash message to a container element on your page
    $("#flash-message-axios").append(flashMessage);
    // Show the flash message
    flashMessage.css("display", "block");
}
/* end of Flash message */



/**
 * Show a toast message with a specified message and type.
 * @param {string} type - The type of the toast ("success", "warning", or "danger").
 * @param {string} message - The message to display in the toast.
 */
function showToastMessage(type, message) {
    const toastLiveExample =  document.getElementById(`${type}Toast`);
    // const bodyElement = toastLiveExample.querySelectorAll('.toast-body')[0];
    const bodyElement = toastLiveExample.querySelector('.toast-body');

    let icon, color;

    switch (type) {
        case 'success':
            icon = 'fa-circle-check';
            color = '--bs-success-rgb';
            break;
        case 'warning':
            icon = 'fa-triangle-exclamation';
            color = '--bs-warning-rgb';
            break;
        case 'danger':
            icon = 'fa-triangle-exclamation';
            color = '--bs-danger-rgb'
            break;
        default:
            console.error("Invalid 'type' argument. Use 'success', 'warning', or 'danger'.");
            return;
    }

    bodyElement.innerHTML = `<i class="fa-solid ${icon}" style="color: rgb(var(${color}));"></i><span class="m-1">${message}</span>`;
    const toastBootstrap = bootstrap.Toast.getOrCreateInstance(toastLiveExample);
    toastBootstrap.show();
}
/* End of Show a toast message with a specified message and type.*/


$(document).ready(function () {

/* Resizing events for Plotly and datatables when the window is resized or the sidebar is toggled*/
let resizeColumnEvent;

// I use this resize event to adjust columns again since now I'm using min-width to the cloned filter and width could be misaligned when window resize
// toggle sidebar in the left will cause misaligned too, call the function when toggle the button
window.onresize = function () {
    clearTimeout(resizeColumnEvent);
    resizeColumnEvent =
        setTimeout(function () {
                $($.fn.dataTable.tables(true)).DataTable()
                    .columns.adjust();
            },
            200);
};

const sidebarToggle = document.body.querySelector('#sidebarToggle');
if (sidebarToggle) {

    // click listener
    sidebarToggle.addEventListener('click', event => {
        clearTimeout(resizeColumnEvent);
        resizeColumnEvent =
            setTimeout(function () {
                    //resize plotly plot
                    const myDiv = document.getElementById('myDiv');
                    if (myDiv) {
                        Plotly.Plots.resize('myDiv')
                    }
                    $($.fn.dataTable.tables(true)).DataTable()
                        .columns.adjust();
                },
                300);
        event.preventDefault();
    });
}
/* end of resize event*/


/* back to top event
source: https://mdbootstrap.com/docs/standard/extended/back-to-top/
*/

//Get the button
let backToTopButton = document.getElementById("btn-back-to-top");

// When the user scrolls down 20px from the top of the document, show the button
window.onscroll = function () {
    scrollFunction();
};

function scrollFunction() {
    if (
        document.body.scrollTop > 20 ||
        document.documentElement.scrollTop > 20
    ) {
        backToTopButton.style.display = "block";
    } else {
        backToTopButton.style.display = "none";
    }
}

// When the user clicks on the button, scroll to the top of the document
backToTopButton.addEventListener("click", backToTop);

function backToTop() {
    document.body.scrollTop = 0;
    document.documentElement.scrollTop = 0;
}
/* end of back to top event*/


/* Switch Yasgui tab event
includes the buttons for copying SPARQL code and SPARQL UPDATE in the Code Editor tab
*/
$('.nav-tabs a').on('shown.bs.tab', function (event) {
    const targetTab = $(event.target).attr("href"); // The activated tab
    if (targetTab === "#sparql_code_view") {
        if (yasgui && yasgui.getTab()) {
            yasgui.getTab().yasqe.refresh();
            showCopyCodeButton(true);
            showUpdateButton(true);
        }
    } else {
        showCopyCodeButton(false);
        showUpdateButton(false);
    }
});

function showCopyCodeButton(show) {
    const copyCodeButton = document.getElementById("copy_code");
    if (copyCodeButton !== null) {
        copyCodeButton.style.display = show ? "block" : "none";
    }
}

function showUpdateButton(show) {
    const updateButton = document.getElementById("updateButton");
    if (updateButton !== null) {
        updateButton.style.display = show ? "inline-block" : "none";
    }
}

// Function to monitor button clicks and handle tab count and the showCopyCodeButton function
function monitorYasguiTabClicks() {
    const tabsList = document.querySelector('.yasgui .tabsList');

    if (tabsList) {
        tabsList.addEventListener('click', function (event) {
            const target = event.target;

            // Check if the clicked element is the add or close button
            const isAddButton = target.classList.contains('addTab');
            const isCloseButton = target.classList.contains('closeTab');

            if (isAddButton || isCloseButton) {
                // Update the tab count based on button clicks
                const numberOfTabs = document.querySelectorAll('.yasgui .tabsList .tab').length;

                // Run the function to show/hide the copy code button based on the tab count
                if (numberOfTabs > 0) {
                    showCopyCodeButton(true); // Show the copy code button
                } else {
                    showCopyCodeButton(false); // Hide the copy code button
                }
            }
        });
    } else {
        showCopyCodeButton(false); // Hide the copy code button
    }
}

monitorYasguiTabClicks()
/* end of Yasgui tab event */


/* Toggle sidebar */
function toggleSidebar() {
    const sidebarToggle = document.getElementById('sidebarToggle');

    if (Boolean(localStorage.getItem('sidebar-toggle-collapsed'))) {
        const body = document.getElementsByTagName('body')[0];
        body.className = body.className + ' sb-sidenav-toggled';
        sidebarToggle.setAttribute('title', 'Keep sidebar visible');
    } else {
        sidebarToggle.setAttribute('title', 'Hide sidebar');
    }

    $('#sidebarToggle').click(function (event) {
        event.preventDefault();
        document.body.classList.toggle('sb-sidenav-toggled');
        const tooltip = bootstrap.Tooltip.getInstance('#sidebarToggle');
        if (Boolean(localStorage.getItem('sidebar-toggle-collapsed'))) {
            localStorage.setItem('sidebar-toggle-collapsed', '');
            tooltip.setContent({'.tooltip-inner': 'Hide sidebar'});
        } else {
            localStorage.setItem('sidebar-toggle-collapsed', '1');
            tooltip.setContent({'.tooltip-inner': 'Keep sidebar visible'});
        }
    });

}

// Call the toggleSidebar function when the page loads
toggleSidebar();

/* end of Toggle sidebar */


/* Tooltip event */
let tooltips = []; // Array to store the tooltips

function initializeTooltip() {
    // Destroy existing tooltips before creating new ones
    destroyTooltips();

    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltips = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

function destroyTooltips() {
    tooltips.forEach(function (tooltip) {
        if (typeof tooltip !== 'undefined' && typeof tooltip !== null) {
            tooltip.dispose(); // Dispose of the tooltip if it's defined and of type 'object'
        }
    });
    tooltips = []; // Clear the tooltips array
}

function triggerHideTooltip() {
    const tooltipTriggerList = $('[data-bs-toggle="tooltip"]');

    tooltipTriggerList.on('click', function () {
        // $(this).blur() // this causes Chrome's autofill tooltip to disappear immediately
        const tooltipInstance = bootstrap.Tooltip.getInstance(this);
        tooltipInstance.hide();
    })
}


initializeTooltip();
triggerHideTooltip();

const copyButtons = [].slice.call(document.querySelectorAll('.copy-button'));

copyButtons.forEach(function (button) {
    button.addEventListener('click', function () {

        // Update the title to 'Copied'
        button.setAttribute('data-bs-original-title', 'Copied');
        $(this).find('i').toggleClass('fa-regular fa-copy').toggleClass('fa-solid fa-check');
        const $this = $(this);  // so this button can be used again in the timeout function

        // Reinitialize the tooltip with the new title
        const tooltipInstance = new bootstrap.Tooltip(button); // so that the tooltip is displayed again even if the mouse is still on the button
        tooltipInstance.show();

        // Delay the restoration of the original title
        setTimeout(function () {
            // Restore the original title
            button.setAttribute('data-bs-original-title', '');
            $this.find('i').toggleClass('fa-solid fa-check').toggleClass('fa-regular fa-copy');

            tooltipInstance.hide();
        }, 1000);
    });

    // Add a touchend event listener for mobile devices
    button.addEventListener('touchend', function (event) {
        event.preventDefault(); // Prevents ghost click
        // Trigger the click event programmatically
        button.click();
    });

});
/* end of Tooltip event */
});








