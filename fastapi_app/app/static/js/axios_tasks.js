let table;
let buttonName;
let fixedColNum; // for query UI with enough width, no fixed column for code editor UI

let mapped_head;
let tableData;

let file;

function updateApiKeyValidToFormat(apiKeyValidToTimestamp) {
    if(apiKeyValidToTimestamp === "-") {
        $("#api_key_valid_to").text(apiKeyValidToTimestamp)
        return;
    }
    let newValidTo = "-";
    try {
        newValidTo = new Date(apiKeyValidToTimestamp * 1000).toLocaleString()
        if (apiKeyValidToTimestamp * 1000 < Date.now()) {
            $("#api_key_valid_to").addClass("text-danger")
        } else {
            $("#api_key_valid_to").removeClass("text-danger")
        }
        showFlashMessage("success", "New API Key generated!", "html", $("#returnMessageContainer"));
    } catch (e) {
        console.error(e)
    }
    $("#api_key_valid_to").text(newValidTo)
}

function createQueryOfNamedGraph(namedGraphIri) {
    yasgui.addTab(true, { ...Yasgui.Tab.getDefaults(), name: "Named Graph Query" }).yasqe.setValue("\PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\nSELECT *\nFROM <" + namedGraphIri + ">\nWHERE {\n  ?sub ?pred ?obj .\n} LIMIT 10");
}

$(document).ready(function () {

    $('[data-toggle="tooltip"]').tooltip();

    $("#named_graphs").DataTable({
        pageLength: 5,
        lengthMenu: [[5, 10, 20], [5, 10, 20]]
    });

    $("#saveKeycloakProviderBtn").click(function (e) {
        e.preventDefault();
        const keycloakProvider = {
            "name": $("#keycloak_name").val(),
            "server_metadata_url": $("#keycloak_server_metadata_url").val(),
            "client_id": $("#keycloak_client_id").val(),
            "client_secret": $("#keycloak_client_secret").val(),
            "enabled": $("#keycloak_enabled").is(":checked")
        };
        axios.post("/admin/users/sso/keycloak", keycloakProvider)
        .then((response) => {
            window.location.reload();
        })
        .catch((e) => {
            showFlashMessage("danger", e.response.data, "html", $("#returnSsoProviderMsgContainer"));
        });
    });

    $("#saveOrcIdProviderBtn").click(function (e) {
        e.preventDefault();
        const orcidProvider = {
            "name": $("#orcid_name").val(),
            "server_metadata_url": $("#orcid_server_metadata_url").val(),
            "client_id": $("#orcid_client_id").val(),
            "client_secret": $("#orcid_client_secret").val(),
            "enabled": $("#orcid_enabled").is(":checked")
        };
        axios.post("/admin/users/sso/orcid", orcidProvider)
        .then((response) => {
            window.location.reload();
        })
        .catch((e) => {
            showFlashMessage("danger", e.response.data, "html", $("#returnSsoProviderMsgContainer"));
        });
    });

    $(".ssoProviderEnabledSwitch").click(function (e) {
        // Get the current state of the switch
        const enabled = $(this).is(":checked");
        const providerId = $(this).attr("data-providerid");
        axios.post("/admin/users/sso/" + providerId + "/enabled", { enabled: enabled })
        .then((response) => {
            if (enabled) {
                showFlashMessage("warning", "SSO Provider enabled!", "html", $("#returnSsoProviderMsgContainer"));
            } else {
                showFlashMessage("warning", "SSO Provider disabled!", "html", $("#returnSsoProviderMsgContainer"));
            }
        })
        .catch((e) => {
            showFlashMessage("danger", e.response.data, "html", $("#returnSsoProviderMsgContainer"));
        });
    });

    $(".deleteSSOProviderBtn").click(function (e) {
        e.preventDefault();
        if (confirm("Are you sure you want to delete this SSO Provider?") === false) {
            return;
        }
        axios.delete("/admin/users/sso/" + $(this).attr("data-providerid"))
        .then((response) => {
            window.location.reload();
        })
        .catch((e) => {
            showFlashMessage("danger", e.response.data, "html", $("#returnSsoProviderMsgContainer"));
        });
    });


    $(".saveUserBtn").click(function (e) {
        e.preventDefault();
        const userRow = $(this).closest(".userRow");
        let newUserObj = {
            "name": $(userRow).find(".editUserName").val(),
            "sso_provider": $(userRow).find(".editUserSSOProvider").val(),
            "user_identifier": $(userRow).find(".editUserIdentifier").val(),
            "user_password": $(userRow).find(".editUserPassword").val(),
            "role": $(userRow).find(".editUserRole").val()
        };
        axios.put("/admin/users/" + $(userRow).attr("data-userid"), newUserObj)
        .then((response) => {
            showFlashMessage("success", "User updated!", "html", $("#returnUsersMsgContainer"));
            $(userRow).find(".editUser").hide();
            $(userRow).find(".editUserHide").show();
            $(userRow).find(".saveUserBtn").hide();
            $(userRow).find(".userName").text(newUserObj.name);
            $(userRow).find(".ssoProviderName").text($(userRow).find(".editUserSSOProvider").children("option").filter(":selected").text());
            $(userRow).find(".userIdentifier").text(newUserObj.user_identifier);
            $(userRow).find(".userRole").text($(userRow).find(".editUserRole").children("option").filter(":selected").text());
        })
        .catch((e) => {
            showFlashMessage("danger", e.response.data, "html", $("#returnUsersMsgContainer"));
        });
    });

    $(".editUserSSOProvider").change(function () {
        if ($(this).val() == "local") {
            $(this).closest(".userRow").find(".editUserPasswordContainer").show();
        } else {
            $(this).closest(".userRow").find(".editUserPasswordContainer").hide();
        }
        $("#editUserIdentifierHelptext").text($(this).children("option").filter(":selected").attr("data-available-identifier-text"));
    });

    $(".editUserBtn").click(function (e) {
        e.preventDefault();
        const userRow = $(this).closest(".userRow");
        $(userRow).find(".editUserHide").hide();
        $(userRow).find(".editUser").show();
        $(userRow).find(".saveUserBtn").show();
        if($(userRow).find(".editUserSSOProvider").val() == "local") {
            $(userRow).find(".editUserPasswordContainer").show();
        } else {
            $(userRow).find(".editUserPasswordContainer").hide();
        }
    });

    $(".deleteUserBtn").click(function (e) {
        const userRow = $(this).closest(".userRow");
        e.preventDefault();
        if (confirm("Are you sure you want to delete this user?") === false) {
            return;
        }
        axios.delete("/admin/users/" + $(userRow).attr("data-userid"))
        .then((response) => {
            window.location.reload();
        }
        ).catch((e) => {
            showFlashMessage("danger", e.response.data, "html", $("#returnUsersMsgContainer"));
        });
    });
        
    if ($("#newUserSSOProvider").val() == "local") {
        $("#newUserPassword").show();
    } else {
        $("#newUserPassword").hide();
    }

    $("#newUserSSOProvider").change(function () {
        if ($("#newUserSSOProvider").val() != "") {
            $("#newUserIdentifier").prop('disabled', false);
            $("#newUserIdentifier").attr('placeholder', "");
            $("#newUserRole").prop('disabled', false);
        }

        if ($("#newUserSSOProvider").val() == "local") {
            $("#newUserPassword").show();
        } else {
            $("#newUserPassword").hide();
        }
        
        $("#userIdentifierFieldDescription").text($("#newUserSSOProvider option:selected").attr("data-available-identifier-text"));
    });

    $(".editSSOProviderNameBtn").click(function (e) {   
        e.preventDefault();
        const ssoProviderRow = $(this).closest(".ssoProviderRow");
        $(ssoProviderRow).find(".editSSOProviderHide").hide();
        $(ssoProviderRow).find(".editSSOProviderName").show();
        $(ssoProviderRow).find(".saveSSOProviderNameBtn").show();
    });

    $(".saveSSOProviderNameBtn").click(function (e) {
        e.preventDefault();
        const ssoProviderRow = $(this).closest(".ssoProviderRow");
        const ssoProviderId = $(ssoProviderRow).attr("data-providerid");
        const newName = $(ssoProviderRow).find(".editSSOProviderName").val();
        axios.put("/admin/users/sso/" + ssoProviderId, { name: newName })
        .then((response) => {
            showFlashMessage("success", response.data, "html", $("#returnSsoProviderMsgContainer"));
            $(ssoProviderRow).find(".ssoProviderName").text(newName);
            $(ssoProviderRow).find(".editSSOProviderHide").show();
            $(ssoProviderRow).find(".editSSOProviderName").hide();
            $(ssoProviderRow).find(".saveSSOProviderNameBtn").hide();
        })
        .catch((e) => {
            showFlashMessage("danger", e.response.data, "html", $("#returnSsoProviderMsgContainer"));
        });
    });

    $("#newUserBtn").click(function (e) {
        e.preventDefault();
        pName = $("#newUserName").val();
        pSsoProvider = $("#newUserSSOProvider").val();
        pUserIdentifier = $("#newUserIdentifier").val();
        pRole = $("#newUserRole").val();
        pPassword = $("#newUserPassword").val();
        if (pName === "") {
            showFlashMessage("warning", "Name must be set", "html", $("#returnUsersMsgContainer"));
            return;
        }
        if (pSsoProvider === "") {
            showFlashMessage("warning", "SSO Provider must be selected", "html", $("#returnUsersMsgContainer"));
            return;
        }
        if (pUserIdentifier === "") {
            showFlashMessage("warning", "User Identifier must be set", "html", $("#returnUsersMsgContainer"));
            return;
        }
        if (pRole === null || pRole === "") {
            showFlashMessage("warning", "Role must be selected", "html", $("#returnUsersMsgContainer"));
            return;
        }
        if(pSsoProvider === "local" && pPassword.length < 8) {
            showFlashMessage("warning", "Password must be at least 8 characters long", "html", $("#returnUsersMsgContainer"));
            return;
        }

        axios.post("/admin/users", {
            name: pName,
            sso_provider: pSsoProvider,
            user_identifier: pUserIdentifier,
            user_password: pPassword,
            role: pRole
        }).then((response) => {
            window.location.reload();
        }).catch((e) => {
            showFlashMessage("danger", e.response.data, "html", $("#returnUsersMsgContainer"));
            $("#restoreModal").modal('hide')
        });
    });

    $("#downloadBackupBtn").click(function (e) {
        e.preventDefault();
        window.location.href = "/admin/backup/backup";
    });

    $("#restoreBackupBtn").click(function (e) {
        e.preventDefault();
        if ($("#restoreBackupForm input[type='file']").val() === "") {
            showFlashMessage("warning", "Please select a backup file first", "html", $("#returnBackupMsgContainer"));
            return;
        }
        if (confirm("Do you really want to restore the selected backup?\n\nNote: All data will be lost, also in case of error!") === false) {
            return;
        }
        // Submit form with axios
        const formData = new FormData($("#restoreBackupForm")[0]);

        $("#restoreModal").modal('show')

        axios.post("/admin/backup/restore", formData, {
            headers: {
                'Content-Type': 'multipart/form-data'
            }
        }).then((response) => {
            window.location = "/";
        }).catch((e) => {
            showFlashMessage("danger", e.response.data, "html", $("#returnBackupMsgContainer"));
            $("#restoreModal").modal('hide')
        });
    });

    $("#cancelBtn").click(function (e) {
        e.preventDefault();
        $(".action-button").show();
        $(".action-loading-elem").hide();
        $("#saveQueryContainer").hide();
        $("#savedQueryMsgContainer").empty();
        $("#cancelBtn").hide();
    });

    $("#saveQueryConfirmBtn").click(function (e) {
        e.preventDefault();
        $("#action-container").show();
        $("#saveQueryContainer").hide();
        $("#savedQueryMsgContainer").empty();
        axios.post("/saved_queries", {
            name: $("#queryName").val(),
            query: yasgui.getTab().yasqe.getValue(),
            public: $("#publicToggle").is(":checked")
        }).then((response) => {
            showFlashMessage("success", "Query successfully saved", "html", $("#savedQueryMsgContainer"), true);
            $(".action-button").show();
            $("#saveQueryContainer").hide();
            $("#cancelBtn").hide();
        }).catch((e) => {
            showFlashMessage("danger", e.response.data, "html", $("#savedQueryMsgContainer"), true);
            console.error(e);
        });
    });

    $("#deleteQueryBtn").click(function (e) {
        e.preventDefault();
        $("#savedQueryMsgContainer").empty();
        const queryId = $("#query_select").val();
        if (confirm("Are you sure you want to delete the selected query?") === false) {
            return;
        }
        axios.delete("/saved_queries/" + queryId).then((response) => {
            $("#query_select option:selected").remove();
            showFlashMessage("success", response.data, "html", $("#savedQueryMsgContainer"), true);
            $(".action-button").show();
            $(".action-loading-elem").hide();
            $("#saveQueryContainer").hide();
            $("#cancelBtn").hide();
        }).catch((e) => {
            showFlashMessage("danger", e.response.data, "html", $("#savedQueryMsgContainer"), true);
            console.error(e);
        });
    });

    $("#loadSelectedQueryBtn").click(function (e) {
        e.preventDefault();
        $("#savedQueryMsgContainer").empty();
        const queryId = $("#query_select").val();
        axios.get("/saved_queries/" + queryId).then((response) => {
            const query = response.data;
            yasgui.addTab(true, { ...Yasgui.Tab.getDefaults(), name: query.name }).yasqe.setValue(query.query);
            $("#cancelBtn").click();
            showFlashMessage("success", "Query \"" + query.name + "\" loaded", "html", $("#savedQueryMsgContainer"), true);
        }).catch((e) => {
            showFlashMessage("danger", e.response.data, "html", $("#savedQueryMsgContainer"), true);
            console.error(e);
        });
    });

    $("#load_query_btn").click(function (e) {
        e.preventDefault();
        $("#savedQueryMsgContainer").empty();
        axios.get("/saved_queries").then((response) => {
            const savedQueries = response.data;
            $("#query_select").empty();
            if (savedQueries.length === 0) {
                showFlashMessage("warning", "No saved queries available", "html", $("#savedQueryMsgContainer"), true);
                return;
            }
            savedQueries.forEach(query => {
                optionName = query.name;
                if (query.public === true) {
                    optionName += " (public)";
                }
                $('<option>').val(query.id).text(optionName).attr('data-can-delete', query.canDelete).appendTo('#query_select');
            });
            $("#query_select").show();
            $("#cancelBtn").show();
            $(".action-loading-elem").show();
            $("#load_query_btn").hide();
            $(".action-save-copy-button").hide();
            $("#query_select").change();
        }).catch((e) => {
            showFlashMessage("danger", e.response.data, "html", $("#savedQueryMsgContainer"), true);
            console.error(e);
        });
    });

    $("#save_query_btn").click(function () {
        $("#savedQueryMsgContainer").empty();
        $("#queryName").val(yasgui.getTab().getName());
        $("#saveQueryContainer").show();
        $("#cancelBtn").show();
        $(".action-button").hide();
    });

    $("#query_select").change(function () {
        $("#savedQueryMsgContainer").empty();
        if ($("#query_select option:selected").attr("data-can-delete") == "true") {
            $("#deleteQueryBtn").show();
        } else {
            $("#deleteQueryBtn").hide();
        }
    });

    $("#password_change_button").click(function () {
        $("#returnPasswordChangeMessageContainer").text("");
        $("#old_password").val("");
        $("#new_password1").val("");
        $("#new_password2").val("");
    });

    $("#api_key_button").click(function () {
        $("#returnMessageContainer").text("");
    });

    updateApiKeyValidToFormat($("#api_key_valid_to").text());

    $("body").on("click", "#api_key_days_valid_refresh", function (e) {
        e.preventDefault();
        axios.get("/refresh_api_key?valid=" + $("#api_key_days_valid").val())
            .then(resp => {
                $("#api_key").val(resp.data.apiKey);
                updateApiKeyValidToFormat(resp.data.validTo)
            })
            .catch((e) => {
                showFlashMessage("danger", e.response.data, "html", $("#returnMessageContainer"));
            })
    });

    $("body").on("click", "#password_change_submit", function (e) {
        e.preventDefault();
        axios.post("/update_password", {old_password: $("#old_password").val(), new_password1: $("#new_password1").val(), new_password2: $("#new_password2").val()})
            .then(resp => {
                showFlashMessage("success", resp.data, "html", $("#returnPasswordChangeMessageContainer"));
            })
            .catch((e) => {
                showFlashMessage("danger", e.response.data, "html", $("#returnPasswordChangeMessageContainer"));
            })
    });

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

        // let graphTitle = document.getElementById("graphTitle");
        console.debug(tab)
        // $('#plotly_wrapper :button').prop('disabled', true);
        // graphTitle.textContent = "Graphs (not available when using the code editor for the query)";
        // Plotly.purge('myDiv');
        // clearOptions();


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

        let action = "query";
        let form_data = jQuery.param({ query: encodeURIComponent("") });
        if (buttonName === "query") {
            action = "query";
            form_data = jQuery.param({ query: requestBody });
        } else if (buttonName === "update") {
            action = "update";
            form_data = jQuery.param({ update: requestBody });
        }

        const url = `/${action}`;
        const queryParams = { tdb_id: tdbId };


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



                $("#table-container").removeClass("d-none");

                const startTime2 = new Date(); // Record the start time

                if ($.fn.DataTable.isDataTable('#table_query')) {
                    $('#table_query').DataTable().clear().destroy();
                }
                $("#table_query thead").remove();
                $('#table_query tbody').remove();
                $('#table_query tfoot').remove();


                //mapping header
                mapped_head = response.data.head.map(headerObject => {
                    return { "title": headerObject.title };
                });
                // console.debug("head=" + JSON.stringify(response.data.head))
                // console.debug("mapped_head=" + JSON.stringify(mapped_head))


                // let fixedColNum; // for query UI with enough width, no fixed column for code editor UI
                if (document.documentElement.clientWidth > 780 && $('.nav-tabs a.nav-link.active').attr("href") === '#query_gui_view') {
                    fixedColNum = 1;
                } else {
                    fixedColNum = 0
                }

                tableData = response.data.data;

                // console.debug('rawData:' + JSON.stringify(response.data.data));

                table = createTable(tableData, mapped_head, tdbId);

                if (!response.data.raw || response.data.raw === 0) {
                    $("#raw_data").val("")
                    $("#raw_data_container").hide();
                } else {
                    $("#raw_data_container").show();
                    $("#raw_data").val(response.data.raw);
                }

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
            // Plotly.purge('myDiv'); // Clear plotly plots after query/update regardless of result
            clearOptions();
        }
    });

    $("#download-trig-file").click(function (e) {
        e.preventDefault();
        window.location.href = $(this).attr("data-url");
    });

    $('#file-selector-rdf-ttl').on("change", function (event) {
        event.preventDefault(); // Prevent the default form submission
        //getting user select file and [0] this means if user selects multiple files then we'll select only the first one
        file = this.files[0];
        const fileName = file.name;
        console.debug("Selected file: " + fileName);
        const fileType = fileName.split('.').pop();
        uploadData(fileType);
        $('#file-selector').val('');
    });

    $('#file-selector-trig').on("change", function (event) {
        event.preventDefault(); // Prevent the default form submission
        //getting user select file and [0] this means if user selects multiple files then we'll select only the first one
        file = this.files[0];
        const fileName = file.name;
        console.debug("Selected file: " + fileName);
        const fileType = fileName.split('.').pop();
        uploadData(fileType);
        $('#file-selector-trig').val('');
    });

    $("#webvowl_show_button").click(function (e) {
        e.preventDefault();
        $(this).attr("disabled", true);
        $(this).text("Generating VOWL, this may take a while, please wait...");
        axios.get("/jena/"+$(this).attr("data-tdb-id")+"/generate_vowl")
        .then((response) => {
            $("#webvowl_container").removeClass("d-none");
            $('#webvowl_iframe').attr('src', $('#webvowl_iframe').attr("data-src"));
            $("#webvowl_available_container").addClass("d-none");
            
        })
        .catch((e) => {
            showFlashMessage("danger", e.response.data, "html");
        });
        
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
                    formData.append('namedGraphUpload', $("#named-graph-upload").val());

                    const tdbId = $("#tdb_id").text();
                    const queryParams = { tdb_id: tdbId };


                    const config = {
                        onUploadProgress: (progressEvent) => {
                            const { loaded, total } = progressEvent;
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

                    $("#dataset_empty_hint").addClass("d-none");
                    $("#webvowl_available_container").removeClass("d-none");
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
            const upload_filesize = file.size / 1024 / 1024;
            showFlashMessage('warning', `Upload filesize: ${Math.trunc(upload_filesize)}MB too large (limit < ${maxSizeInBytes / 1024 / 1024}MB)`, 'html')
        }
    }

});

function clearOptions() {
    $("#xaxis").empty();
    $("#yaxis").empty();
    $("#propertyMenu").empty();
    $("#xaxis").parent().hide();
    $("#yaxis").parent().hide();
    $("#propertyMenu").parent().hide();
    $("#oxideList").parent().hide();
}


function createTable(data, mapped_head, tdbId) {
    const today = new Date();
    const dd = String(today.getDate()).padStart(2, '0');
    const mm = String(today.getMonth() + 1).padStart(2, '0'); //January is 0!
    const yyyy = today.getFullYear();

    const today_format = dd + '' + mm + '' + yyyy;

    let tooltip = false;

    console.debug(data)
    console.debug(mapped_head)

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
                    // {
                    //     className: 'btn btn-outline-secondary rounded-start rounded-end',
                    //     extend: 'copyHtml5',
                    //     exportOptions: {
                    //         columns: [0, ':visible']
                    //     },
                    //     text: '<i class="fi fi-rr-duplicate align-middle"></i><span class="ms-1">Copy</span>',
                    //     title: '',
                    // },
                    // {
                    //     extend: 'spacer',
                    //     style: 'mx-1',
                    // },
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

                    $(this).css("min-width", 130);

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

