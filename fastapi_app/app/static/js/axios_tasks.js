let table;
let buttonName;
let query_ui_mode = false; // if false, disable the plot functions
let fixedColNum; // for query UI with enough width, no fixed column for code editor UI

let mapped_head;
let rawData;

let file;

$(document).ready(function () {

// Add a click event listener to the buttons inside the form
    $("[form='qform']").on("click", function () {
        buttonName = $(this).attr("name");
    });

    $("#qform").submit(async function (event) {
        event.preventDefault(); // Prevent the default form submission

        const startTime = new Date(); // Record the start time

        const tdbId = $("#tdb_id").text();

        const tab = $('.nav-tabs a.nav-link.active').attr("href");

        let requestBody, message;

        let graphTitle = document.getElementById("graphTitle");

        if (tab === "#sparql_code_view") {
            query_ui_mode = false;
            $('#plotly_wrapper :button').prop('disabled', true);
            graphTitle.textContent = "Graphs (not available when using the code editor for the query)";
            Plotly.purge('myDiv');
            clearOptions();


            console.debug("Open Yasgui Code Editor")
            requestBody = yasgui && yasgui.getTab() && yasgui.getTab().yasqe.getValue();
            if (!requestBody) {
                // const emptyMessage = "SPARQL Query: Empty query string";
                const emptyMessage = `
                    <i class="fa-solid fa-triangle-exclamation" style="color: rgb(var(--bs-warning-rgb));"></i>
                    <span class='ms-1'>SPARQL Query: Empty query string
                    </span>
                    `;
                showFlashMessage("warning", emptyMessage, "html");
                return false;
            }
        } else {
            query_ui_mode = true;

            console.debug("Directly generate code from Query UI");

            [requestBody, message] = generate_SPARQL_code(tdbId);
            if (!requestBody) {
                const Message = `
                    <i class="fa-solid fa-triangle-exclamation" style="color: rgb(var(--bs-warning-rgb));"></i>
                    <span class='ms-1'>${message}
                    </span>
                    `;
                showFlashMessage("warning", Message, "html");
                return false;
            } else {
                $('#plotly_wrapper :button').prop('disabled', false);
                graphTitle.textContent = "Graphs";
                if (selectedOxides.length !== 3) {
                    $('#ternary_plot').prop('disabled', true);
                    graphTitle.textContent = "Graphs (Ternary Plot will be activated when you choose ternary glass systems)";
                } else {
                    $('#ternary_plot').prop('disabled', false);
                    graphTitle.textContent = "Graphs";
                }
            }
        }

        let action = "query";
        let form_data = jQuery.param({query: encodeURIComponent("")});
        if (buttonName === "query") {
            action = "query";
            form_data = jQuery.param({query: requestBody});
        } else if (buttonName === "update") {
            action = "update";
            form_data = jQuery.param({update: requestBody});
        }

        const url = `/${action}`;
        const queryParams = {tdb_id: tdbId};


        const waitingMessage = setInterval(() => console.debug('Still waiting...'), 1000);

        const runningMessage = "<span class='spinner-border spinner-border-sm' role='status' aria-hidden='true'></span>";
        showFlashMessage("success", runningMessage, "html");


        // disable Query/Update button
        $(document.getElementsByName(buttonName)).prop('disabled', true);

        try {

            const response = await axios.post(url, form_data, {
                params: queryParams,
                // headers: {
                //     Authorization: 'Bearer your_token_here',
                // },
            });


            if (action === "query") {
                console.debug('Query OK. Start to load results into table')

                const startTime2 = new Date(); // Record the start time

                if ($.fn.DataTable.isDataTable('#table_query')) {
                    $('#table_query').DataTable().clear().destroy();
                }
                $("#table_query thead").remove();
                $('#table_query tbody').remove();
                $('#table_query tfoot').remove();


                //mapping header
                mapped_head = response.data.head.map(headerObject => {
                    if (tdbId === 'SciGlass') {
                        return {"title": sciglass_mapping[headerObject.title] || headerObject.title};
                    } else {
                        return {"title": headerObject.title};
                    }
                });
                // console.debug("head=" + JSON.stringify(response.data.head))
                // console.debug("mapped_head=" + JSON.stringify(mapped_head))

                //mapping properties
                if (selectedProps.length > 0) {
                    selectedProps = selectedProps.map(property => {
                        return sciglass_mapping[property] || property;
                    });
                    // console.debug("mapped_properties=" + selectedProps)
                }

                // let fixedColNum; // for query UI with enough width, no fixed column for code editor UI
                if (document.documentElement.clientWidth > 780 && $('.nav-tabs a.nav-link.active').attr("href") === '#query_gui_view') {
                    fixedColNum = 1;
                } else {
                    fixedColNum = 0
                }

                rawData = response.data.data;

                // console.debug('rawData:' + JSON.stringify(response.data.data));

                table = createTable(rawData, mapped_head, tdbId);

                if ($('.nav-tabs a.nav-link.active').attr("href") === '#query_gui_view') {
                    table.on('column-visibility.dt', function () {
                        $('[data-bs-custom-class="custom-tooltip"]').tooltip()
                    });
                    $('[data-bs-custom-class="custom-tooltip"]').tooltip()
                }

                endTime = new Date();
                processTime = (endTime - startTime) / 1000; // Calculate the process time in seconds
                const processTime2 = (endTime - startTime2) / 1000; // Calculate the process time in seconds
                const queryTime = (startTime2 - startTime) / 1000;
                console.debug("Process time (query): " + queryTime + " seconds");
                console.debug("Process time (table): " + processTime2 + " seconds");

                const successMessage = `
                <i class="fa-solid fa-circle-check" style="color: rgb(var(--bs-success-rgb));"></i>
                <span class='ms-1'>Query success in ${processTime} seconds.
                </span>
                `;
                showFlashMessage("success", successMessage, "html");

            } else if (buttonName === "update") {
                endTime = new Date(); // Record the end time
                processTime = (endTime - startTime) / 1000; // Calculate the process time in seconds

                console.debug("Process time (update): " + processTime + " seconds");
                const successMessage = `
                <i class="fa-solid fa-circle-check" style="color: rgb(var(--bs-success-rgb));"></i>
                <span class='ms-1'>Update success in ${processTime} seconds.
                </span>
                `;
                showFlashMessage("success", successMessage, "html");


            }

            // console.debug('response.data:' + response.data.data);

            // enable Query/Update button again
            $(document.getElementsByName(buttonName)).prop('disabled', false);

            // Clear the waiting message interval
            clearInterval(waitingMessage);

            console.debug("Process time (total): " + processTime + " seconds");
            console.debug('Successfully finished');


        } catch (error) {
            console.debug("Error occurs:");
            console.error(error);
            let parsed_error;

            if (error?.response?.data == null || error?.response?.data === '') {
                parsed_error = error.message;
            } else {
                parsed_error = error.response.data; //Error message from backend
            }

            // enable Query/Update button again
            $(document.getElementsByName(buttonName)).prop('disabled', false);

            // Clear the waiting message interval
            clearInterval(waitingMessage);

            console.debug("Caused by:");
            console.error(parsed_error);


            if (parsed_error === "Query timeout" || parsed_error === "Access forbidden (admin only for now)") {
                const errorMessage = `
                    <i class="fa-solid fa-triangle-exclamation" style="color: rgb(var(--bs-warning-rgb));"></i>
                    <span class='ms-1'>${parsed_error}
                    </span>
                    `;
                showFlashMessage("warning", errorMessage, "html");
            } else {
                // const errorMessage = "Error:<br>" + parsed_error;
                const errorMessage = `
                    <i class="fa-solid fa-triangle-exclamation" style="color: rgb(var(--bs-danger-rgb));"></i>
                    <span class='ms-1'>${parsed_error}
                    </span>
                    `;
                showFlashMessage("danger", errorMessage, "html");
            }

        } finally {
            Plotly.purge('myDiv'); // Clear plotly plots after query/update regardless of result
            clearOptions();
        }
    });


    $('#file-selector').on("change", function (event) {
        // event.preventDefault(); // Prevent the default form submission
        //getting user select file and [0] this means if user selects multiple files then we'll select only the first one
        file = this.files[0];
        const fileName = file.name;
        console.debug("Selected file: " + fileName);
        const fileType = fileName.split('.').pop();
        uploadData(fileType);
        $('#file-selector').val('');
    });

    async function uploadData(fileType) {
        const startTime = new Date(); // Record the start time
        let endTime;
        // Record the end time
        let processTime;

        let percentCompleted = 0;

        console.debug("fileType = " + fileType)

        const maxSizeInBytes = 100 * 1024 * 1024; // 100MB in bytes
        if (file.size <= maxSizeInBytes) {

            let validExtensions = ["rdf", "ttl"]; //adding valid extensions in array
            if (validExtensions.includes(fileType)) { //if user selected file is a .ttl or .rdf
                let fileReader = new FileReader(); //creating new FileReader object
                fileReader.onload = async (event) => {
                    const url = "/upload";

                    clearInterval(loadingMessageDebug);

                    // Display "Uploading to server..." message in the console
                    const uploadingMessageDebug = setInterval(() => console.debug('Uploading...'), 1000);

                    try {
                        // Create a FormData object and append the file to it
                        let formData = new FormData();
                        formData.append('file', file, file.name);

                        const tdbId = $("#tdb_id").text();
                        const queryParams = {tdb_id: tdbId};


                        const config = {
                            onUploadProgress: (progressEvent) => {
                                const {loaded, total} = progressEvent;
                                percentCompleted = Math.round((loaded * 100) / total);
                                if (percentCompleted < 100) {
                                    console.debug(`Upload progress: ${percentCompleted}%`);
                                    const uploadingMessage = `
                                            <i class="fa-solid fa-arrow-up-from-bracket"></i>
                                            <span class='ms-1'>Uploading to server...
                                            </span>
                                            <div class="progress" role="progressbar" aria-label='Example with label' aria-valuenow='${percentCompleted}%' aria-valuemin='0' aria-valuemax='100'>
                                            <div class='progress-bar' style='width: ${percentCompleted}%'>${percentCompleted}%</div>
                                            </div>
                                            `;
                                    showFlashMessage("success", uploadingMessage, "html");
                                } else {
                                    // Clear the uploading message interval
                                    clearInterval(uploadingMessageDebug);
                                    console.debug(`Analyzing the data...`);
                                    const analyzingMessage = "<span class='spinner-border spinner-border-sm m-1' role='status' aria-hidden='true'></span>Analyze file...";
                                    showFlashMessage("info", analyzingMessage, "html");
                                }
                            },
                            params: queryParams,
                            headers: {
                                'Content-Type': 'multipart/form-data'
                            }
                        };


                        //using fileReader to upload
                        const response = await axios.post(url, formData, config);

                        console.debug("Verifying data...")

                        endTime = new Date();
                        processTime = (endTime - startTime) / 1000; // Calculate the process time in seconds

                        const successMessage = `
                        <i class="fa-solid fa-circle-check" style="color: rgb(var(--bs-success-rgb));"></i>
                        <span class='ms-1'>Complete in ${processTime} seconds.
                        </span>
                        `;
                        showFlashMessage("success", successMessage, "html");

                        console.debug('Successfully finished');

                    } catch (error) {
                        endTime = new Date();
                        processTime = (endTime - startTime) / 1000; // Calculate the process time in seconds

                        console.debug("Error:");
                        console.error(error);

                        let parsed_error;

                        console.debug("Caused by:");


                        if (error?.response?.data == null) {
                            parsed_error = "Unexpected unknown error"
                            // const errorMessage = parsed_error;
                            const errorMessage = `
                            <i class="fa-solid fa-triangle-exclamation" style="color: rgb(var(--bs-danger-rgb));"></i>
                            <span class='ms-1'>${parsed_error}
                            </span>
                            `;
                            showFlashMessage("danger", errorMessage, "html");
                        } else {
                            parsed_error = error.response.data;

                            console.debug("parsed_error", parsed_error)

                            if (parsed_error === "Query timeout" || parsed_error === "Access forbidden (admin only for now)") {
                                const errorMessage = `
                            <i class="fa-solid fa-triangle-exclamation" style="color: rgb(var(--bs-warning-rgb));"></i>
                            <span class='ms-1'>${parsed_error}
                            </span>
                            `;
                                showFlashMessage("warning", errorMessage, "html");
                            } else {
                                // const errorMessage = "Error:<br>" + parsed_error;
                                const errorMessage = `
                            <i class="fa-solid fa-triangle-exclamation" style="color: rgb(var(--bs-danger-rgb));"></i>
                            <span class='ms-1'>${parsed_error}
                            </span>
                            `;
                                console.debug("errorMessage", errorMessage)
                                showFlashMessage("danger", errorMessage, "html");
                            }
                        }
                        console.error(parsed_error);


                    } finally {
                        console.debug("Process time (total): " + processTime + " seconds");
                    }
                };


                fileReader.readAsDataURL(file);

                // Display "Loading file..." message in the console
                const loadingMessageDebug = setInterval(() => console.debug('Loading file...'), 1000);

                const loadingMessage = "<span class='spinner-border spinner-border-sm m-1' role='status' aria-hidden='true'></span>Loading file...";
                showFlashMessage("success", loadingMessage, "html");


            } else {
                showToastMessage('warning', 'Oops, you can only upload files in Turtle (.ttl), RDF (.rdf) format.')
            }
        } else {
            const upload_filesize = file.size / 1024 / 1024;
            showToastMessage('warning', `Upload filesize: ${Math.trunc(upload_filesize)}MB too large (limit < ${maxSizeInBytes / 1024 / 1024}MB)`)
        }
    }

});

function clearOptions() {
    $("#xaxis").empty();
    $("#yaxis").empty();
    $("#propertyMenu").empty();
    $("#glassIdMenu").empty();
    $("#xaxis").parent().hide();
    $("#yaxis").parent().hide();
    $("#propertyMenu").parent().hide();
    $("#glassIdMenu").parent().hide();
    $("#oxideList").parent().hide();
}


function createTable(data, mapped_head, tdbId) {
    const today = new Date();
    const dd = String(today.getDate()).padStart(2, '0');
    const mm = String(today.getMonth() + 1).padStart(2, '0'); //January is 0!
    const yyyy = today.getFullYear();

    const today_format = dd + '' + mm + '' + yyyy;

    let tooltip = false;


    return $('#table_query')
        .DataTable({
            language: {
                searchBuilder: {
                    button: {
                        0: '<i class="fi fi-rr-filter align-middle"></i><span class="ms-1">Filter</span><span class="ms-2"><i class="fi fi-rr-angle-small-down align-middle"></i></span>',
                        _: '<i class="fi fi-rr-filter align-middle" style="color: #509ee3;"></i><span class="ms-1" style="color: #509ee3;">Filter (%d)</span><span class="ms-2"><i class="fi fi-rr-angle-small-down align-middle"></i></span>'

                    },
                    title: {
                        0: 'Filter by',
                        _: 'Filter by'
                    },
                }
            },
            processing: true,
            // deferRender: true, //note that this will not write to DOM all at once
            destroy: true,
            // see: https://datatables.net/reference/option/dom
            dom: "Bfrti",
            buttons: {
                dom: {
                    button: {
                        tag: 'button',
                        className: ''
                    }
                },
                buttons: [
                    {
                        className: 'btn btn-outline-secondary rounded-start rounded-end',
                        extend: 'searchBuilder',
                    },
                    {
                        extend: 'spacer',
                        style: 'mx-1',
                    },
                    {
                        className: 'btn btn-outline-secondary rounded-start rounded-end',
                        extend: 'copyHtml5',
                        exportOptions: {
                            columns: [0, ':visible']
                        },
                        text: '<i class="fi fi-rr-duplicate align-middle"></i><span class="ms-1">Copy</span>',
                        title: '',
                    },
                    {
                        extend: 'spacer',
                        style: 'mx-1',
                    },
                    {
                        className: 'btn btn-outline-secondary rounded-start rounded-end',
                        extend: 'collection',
                        text: '<i class="fi fi-rr-download align-middle"></i><span class="ms-2"><i class="fi fi-rr-angle-small-down align-middle"></i></span>',
                        buttons: [
                            {
                                extend: 'csvHtml5',
                                exportOptions: {
                                    columns: ':visible'
                                },
                                filename: 'export-csv-' + today_format,
                                text: '<i class="fi fi-rr-file-csv align-middle"></i><span class="ms-1">.csv</span>',
                                title: '',
                                charset: 'utf-8',
                            },
                            {
                                extend: 'excelHtml5',
                                exportOptions: {
                                    columns: [0, ':visible']
                                },
                                filename: 'export-excel-' + today_format,
                                text: '<i class="fi fi-rr-file-excel align-middle"></i><span class="ms-1">.xlsx</span>',
                                title: '',
                                charset: 'utf-8',
                            },
                        ]
                    },
                ]
            },
            scrollY: 400,
            scrollX: true,
            scroller: {
                loadingIndicator: true
            },
            scrollCollapse: true, //Allow the table to reduce in height when a limited number of rows are shown
            orderCellsTop: true,
            fixedColumns: {
                left: fixedColNum,
            },
            responsive: false,
            autoWidth: false,
            select: true,
            "data": data,
            "columns": mapped_head,

            "initComplete": function () {
                $('#table_query_wrapper .dropdown-toggle').removeClass('dropdown-toggle') // hide default dropdown-toggle arrow icon

                // use .dataTables_scrollHead instead of table_query when having scrollX: true otherwise, filter will disappear when typing or resize
                // Don't use clone as example https://datatables.net/extensions/fixedheader/examples/options/columnFiltering.html
                // since the sorting is created for the headers, filter will have sorting when using clone
                const api = this.api();

                api.columns().header().to$().each(function (index) {

                    if ($('.nav-tabs a.nav-link.active').attr("href") === '#query_gui_view') {
                        let indexOffset;
                        if (tdbId === 'SciGlass') {
                            indexOffset = 1;
                        } else {
                            indexOffset = 0;
                        }
                        if (index > indexOffset && index < selectedOxides.length + indexOffset + 1) {
                            const text = $(api.column(index).header()).text();
                            $(api.column(index).header()).text(text + " (mol%)");
                        }
                    }

                    if ($(this).width() >= 30) {
                        $(this).css("min-width", $(this).width());
                    } else {
                        $(this).css("width", 30);
                        $(this).css("min-width", 30);
                    }

                })

                const header = api.columns().header().map(d => d.textContent).toArray();
                const referenceIndex = header.indexOf("Reference");

                // unpack reference and add tooltip for reference column
                // TODO disable tooltip to have best performance
                if (referenceIndex !== -1) {
                    api.rows().every(function () {
                        const rowNode = this.node();
                        const cell = $(rowNode).find('td').eq(referenceIndex); // or .last() in this case, reference column is the last column
                        let cellValue = cell.text();
                        const datas = cellValue.split('\n');
                        let ref = '';
                        if (datas[0].indexOf('None') === -1) {
                            ref += datas[0].substring(7);
                            if (ref.charAt(ref.length - 1) !== '.') {
                                ref += '.';
                            }
                        }

                        if (datas[1] && datas[1].indexOf('None') === -1) {
                            ref += datas[1].substring(12);
                            if (datas[0].indexOf('None') !== -1) {
                                ref = ref.substring(1);
                            }
                        }

                        cellValue = ref;
                        cell.text(cellValue); // Replacing cell values with unpacked reference text

                        cell
                            .css("min-width", "200px")
                            .css("max-width", "200px")
                            .css("white-space", "nowrap")
                            .css("overflow", "hidden")
                            .css("text-overflow", "ellipsis")
                            .attr('data-bs-custom-class', 'custom-tooltip')
                            .attr('data-bs-placement', 'top')
                            .attr('title', cellValue);
                    });

                    $('.dataTables_scrollHead thead tr').each(function () {
                        $(this).find('th').eq(referenceIndex)
                            .css("min-width", "200px")
                    })

                    // set tooltip boolean variable to true
                    tooltip = true;

                }


                // use this when having scrollX enabled
                $('.dataTables_scrollHead thead tr')
                    .clone(false) // set false to disable sorting
                    .addClass('filters')
                    .appendTo('.dataTables_scrollHead thead');

                // For each column
                api
                    .columns()
                    .eq(0)
                    .each(function (colIdx) {

                        // Set the header cell to contain the input element
                        const cell = $('.filters').last().find('th').removeClass().eq(
                            $(api.column(colIdx).header()).index()
                        );

                        const title = "search" // filter
                        $(cell).html('<input type="search" class="form-control form-control-sm" placeholder="' + title + '" />');

                        $('input', $('.filters').last().find('th').eq($(api.column(colIdx).header()).index()))
                            .on('input', function (e) {
                                api.column(colIdx).search(this.value, false, true).draw();
                            });
                    });

                api.columns.adjust(); // Adjust column width after narrowing the column
            },
            // This function is called whenever the table is drawn or redrawn, including when a new search is performed, paging is changed, or sorting is applied
            drawCallback: function (settings) {
                // Reinitialize tooltips after the table is redrawn
                if (tooltip) {
                    $('[data-bs-custom-class="custom-tooltip"]').tooltip(); // so that the tooltip for the remaining rows will be shown
                }

            }
        });
}

