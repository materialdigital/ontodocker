/* These plotting functions are customized for the GlasDigital demo case.
This means that they are not general plotting functions for all cases.
You will most likely need to modify the script before using other types of data.
 */


// scatter (for single trace)
function scatterStandOutOnHover() {
    let hoveredTraceIndex = -1; // Initialize with an invalid index

    let initialOpacity;

    const oxideListItems = document.querySelectorAll('#oxideList li');

    document.getElementById('myDiv').on('plotly_hover', function (data) {
        const points = data.points;  // Get the hovered points
        const pointIndex = points[0].pointIndex;

        hoveredTraceIndex = points[0].pointNumber;

        const datapoints = points[0].data.x.length;

        // console.log("data", data);
        // console.log("data.points", data.points);
        // console.log("hoveredTraceIndex", hoveredTraceIndex);
        // console.log("pointIndex", pointIndex);
        // console.log("points[0].customdata", points[0].customdata);
        oxideListItems.forEach((li, index) => {

            li.childNodes[0].nodeValue = li.childNodes[0].nodeValue.split(': ')[0] + ': ' + `${points[0].customdata[index + 1]}`; // skip the glass No., since I need the rest oxide mol%
        });

        initialOpacity = Array(datapoints).fill(0.1);

        // Set the opacity of the hovered trace to 1 (fully visible)
        initialOpacity[pointIndex] = 1;

    });

    document.getElementById('myDiv').on('plotly_unhover', function () {

        // console.log("points[0].customdata", points[0].customdata);

        oxideListItems.forEach((li, index) => {

            li.childNodes[0].nodeValue = li.childNodes[0].nodeValue.split(': ')[0] + ': '; // clear the oxide mol%
        });

    });
}

// histogram (for single trace)
function histogramStandOutOnHover() {

    let initialOpacity;

    document.getElementById('myDiv').on('plotly_hover', function (data) {
        const points = data.points;  // Get the hovered points
        // console.log("data.points", data.points);

        const hoveredBinIndex = points[0].binNumber;
        const xbins = points[0].fullData.xbins;

        // Calculate the bin number range
        const binStart = xbins.start;
        const binEnd = xbins.end;
        const binSize = xbins.size;

        // Calculate the number of bins
        const numBins = Math.ceil((binEnd - binStart) / binSize);

        initialOpacity = Array(numBins).fill(0.25); // same as the hover effect in metabase

        // Set the opacity of the hovered trace to 1 (fully visible)
        initialOpacity[hoveredBinIndex] = 1;


        // Update the marker properties
        Plotly.restyle('myDiv', { //Plotly.update
            'marker.opacity': [initialOpacity],
        });

    });
    document.getElementById('myDiv').on('plotly_unhover', function (data) {
        Plotly.restyle('myDiv', {
            'marker.opacity': 1,
        });
    });

}


function assignOptions(textArray, xSelector, ySelector, propertySelector) {
    for (let i = 0; i < textArray.length; i++) {
        const currentOption = document.createElement('option');
        currentOption.text = textArray[i];
        xSelector.appendChild(currentOption);
        const clonedOption = currentOption.cloneNode(true);
        ySelector.appendChild(clonedOption);
        if (i === 1) {
            clonedOption.setAttribute('selected', 'selected');
        }
        const clonedOption2 = currentOption.cloneNode(true);
        propertySelector.appendChild(clonedOption2);
    }
}


function arraysAreEqual(arr1, arr2) {
    if (arr1.length !== arr2.length) {
        return false;
    }

    for (let i = 0; i < arr1.length; i++) {
        if (arr1[i] !== arr2[i]) {
            return false;
        }
    }

    return true;
}


function setScatterPlot() {
    //if use deferRender:
    const header = mapped_head.map(item => item.title);
    const xAxisSelector = document.getElementById('xaxis');
    const yAxisSelector = document.getElementById('yaxis');
    const propertyOptionSelector = document.getElementById('propertyMenu');

    const xOtions = [...xAxisSelector].map(el => el.value);
    const yOtions = [...yAxisSelector].map(el => el.value);


    if (!arraysAreEqual(xOtions, selectedProps) || !arraysAreEqual(yOtions, selectedProps)) {
        $("#xaxis").empty();
        $("#yaxis").empty();
        assignOptions(selectedProps, xAxisSelector, yAxisSelector, propertyOptionSelector);
    }

    // for SciGlass
    let glassIDNumber = [];

    const data = []; // for SciGlass
    let total;

    glassIDNumber = rawData.map(row => row[header.indexOf("GlasNo")]).map(Number);

    const oxideList = document.getElementById("oxideList");
    oxideList.innerHTML = '';
    selectedOxides.map(function (oxide, i) {
        //if use deferRender:
        data[i] = rawData.map(x => Number(x[header.indexOf(oxide)]));
        const li = document.createElement("li");
        li.className = "list-group-item";
        li.appendChild(document.createTextNode(oxide + " (mol%): "));
        oxideList.appendChild(li);
    });

    total = rawData.map(x => Number(x[header.indexOf('Total (mol%)')]));
    const li = document.createElement("li");
    li.className = "list-group-item";
    li.appendChild(document.createTextNode("Total (mol%): "));
    oxideList.appendChild(li);

    const trace1 = {
        //if use deferRender:
        x: rawData.map(function (x) {
            return x[header.indexOf(xAxisSelector.value)];
        })
            .map(Number),
        y:
            rawData.map(function (y) {
                return y[header.indexOf(yAxisSelector.value)];
            })
                .map(Number),
        mode: 'markers',
        type: 'scatter',
        name: '',
        marker: {
            size: 10,
            opacity: 0.75,
            line: {
                color: 'black',
                width: 1
            }
        },
        customdata: (typeof selectedOxides) != 'undefined' ?
            Array.from({length: data[0].length},
                (_, i) => [glassIDNumber[i], ...data.map(subArray => subArray[i]), total[i]]
            ) : '',
        hovertemplate:
            `(%{x:.3f}, %{y:.3f})` +
            "<extra>GlasNo: %{customdata[0]}</extra>"
    };

    const traces = [trace1];

    const layout = {
        title: {
            text: (typeof selectedOxides) != 'undefined' ?
                '<b>' + selectedOxides.join(' – ') + '</b>' + '<br>' + `${xAxisSelector.value} vs ${yAxisSelector.value}`
                : `${xAxisSelector.value} vs ${yAxisSelector.value}`,
            xref: 'paper',
        },
        xaxis: {
            tickformat: ".2f",
            title: xAxisSelector.value,
            automargin: true,
        },
        yaxis: {
            tickformat: ".2f",
            title: {
                text: yAxisSelector.value,
                standoff: 20
            },
            automargin: true,
        },
        hoverlabel: {
            bgcolor: 'rgb(255,255,255)', // alpha channel has not effect
            namelength: -1,  // -1 shows the whole name regardless of length
            font: {
                size: 16
            },
        },

    };

    const config = {responsive: true};

    Plotly.newPlot('myDiv', traces, layout, config);

    scatterStandOutOnHover()

}


$("#scatter_plot").on('click', function () {
    if (typeof table == 'undefined') {
        showToastMessage('warning', 'Please make a SPARQL query first');
    } else if (table.rows().count() === 0) {
        showToastMessage('warning', 'No data available in table');

    } else {
        OptionsToShowOrHide(["#xaxis", "#yaxis", "#oxideList"], ["#propertyMenu", "#glassIdMenu", "#processParameterMenu"])

        setScatterPlot()
        $('#xaxis, #yaxis').off('change').on('change', function () {
            setScatterPlot();
            $("#propertyMenu").val(this.value);
        });
    }
});


function setHistogramPlot() {
    //if use deferRender:
    const header = mapped_head.map(item => item.title);

    const xAxisSelector = document.getElementById('xaxis');
    const yAxisSelector = document.getElementById('yaxis');
    const propertyOptionSelector = document.getElementById('propertyMenu');

    const xOtions = [...xAxisSelector].map(el => el.value);
    const yOtions = [...yAxisSelector].map(el => el.value);

    if (!arraysAreEqual(xOtions, selectedProps) || !arraysAreEqual(yOtions, selectedProps)) {
        $("#xaxis").empty();
        $("#yaxis").empty();
        assignOptions(selectedProps, xAxisSelector, yAxisSelector, propertyOptionSelector);
    }

    let trace1 = {
        //if use deferRender:
        x: rawData.map((x) => {
            return Number(x[header.indexOf(xAxisSelector.value)]);
        }),
        autobinx: false,
        marker: {
            color: "rgb(80, 158, 227)",
            line: {
                color: "rgb(255, 255, 255)",
                width: 1
            }
        },
        type: "histogram",
        name: "",
        // showlegend: true, // set true to show legend of trace when single trace
    };

    const traces = [trace1];

    const updatemenus = [];

    const layout = {
        title: {
            text: (typeof selectedOxides) != 'undefined' ?
                '<b>' + selectedOxides.join(' – ') + '</b>' + '<br>' + `Histogram of ${xAxisSelector.value}`
                : `Histogram of ${xAxisSelector.value}`,
            // automargin: true,
            xref: 'paper',
        },
        xaxis: {
            tickformat: ".2f",
            title: xAxisSelector.value,
            automargin: true, // TODO Too many auto-margin redraws may occurs when screen width changed
        },
        yaxis: {
            tickformat: "d",
            title: {
                text: "Count",
                standoff: 20
            },
            automargin: true,
            // fixedrange: true, // Can be inconvenient if there are outliers, so set to false
        },

        barmode: 'group',
        bargap: 0.15,
        bargroupgap: 0.1,

        hoverlabel: {
            bgcolor: 'rgba(255,253,250,0.5)', // alpha channel has not effect
            namelength: -1,  // -1 shows the whole name regardless of length
            font: {
                size: 16
            },
        },
        opacity: 0.75, // set opacity for barmode overlay
        updatemenus: updatemenus,

    };

    const config = {responsive: true};

    Plotly.newPlot('myDiv', traces, layout, config);

    histogramStandOutOnHover()

}


$("#histogram_plot").on('click', function () {
    if (typeof table == 'undefined') {
        showToastMessage('warning', 'Please make a SPARQL query first');
    } else if (table.rows().count() === 0) {
        showToastMessage('warning', 'No data available in table');
    } else {
        OptionsToShowOrHide(["#xaxis"], ["#yaxis", "#oxideList", "#propertyMenu", "#glassIdMenu", "#processParameterMenu"])

        setHistogramPlot()
        $('#xaxis, #yaxis').off('change').on('change', function () {
            setHistogramPlot();
            $("#propertyMenu").val(this.value);
        });
    }
});


function setTernaryPlot() {
    //if use deferRender:
    const header = mapped_head.map(item => item.title);
    const tdbId = window.location.href.split('/').pop();
    const data = [];

    selectedOxides.map(function (oxide, i) {
        //if use deferRender:
        data[i] = rawData.map(x => Number(x[header.indexOf(oxide)]));
    });


    const xAxisSelector = document.getElementById('xaxis');
    const yAxisSelector = document.getElementById('yaxis');
    const propertyOptionSelector = document.getElementById('propertyMenu');

    const options = [...propertyOptionSelector].map(el => el.value);

    if (!arraysAreEqual(options, selectedProps)) {
        $("#propertyMenu").empty();
        assignOptions(selectedProps, xAxisSelector, yAxisSelector, propertyOptionSelector);
    }

    // for SciGlass
    let glassIDNumber = [];
    glassIDNumber = rawData
        .map(row => row[header.indexOf("GlasNo")])
        .map(Number);

    const trace1 = {
        type: 'scatterternary',
        mode: 'markers',
        a: data[0],
        b: data[1],
        c: data[2],
        marker: {
            size: 10,
            line: {
                color: "black",
                width: 1
            },
            opacity: 0.5, // In the case of a point superposition, we can tell that there are two points
            //if use deferRender:
            color: propertyOptionSelector.value !== '' ?
                rawData.map(x => Number(x[header.indexOf(propertyOptionSelector.value)]))
                :
                ''
            ,
            colorbar: {
                title: propertyOptionSelector.value,
                xref: 'paper',
                x: 1.2,
            },
        },
        customdata: glassIDNumber,

        hovertemplate:
            `<b>${propertyOptionSelector.value}: %{marker.color:.3f}</b><br>` +
            `GlasNo: %{customdata}<br>` +
            `${selectedOxides[0]}: %{a:.3f} mol%<br>` +
            `${selectedOxides[1]}: %{b:.3f} mol%<br>` +
            `${selectedOxides[2]}: %{c:.3f} mol%<br>` +
            "<extra></extra>"
    };

    const traces = [trace1];

    const layout = {
        hoverlabel: {
            namelength: -1,  // -1 shows the whole name regardless of length
            font: {
                size: 16
            },
        },
        ternary: {
            sum: 100,
            aaxis: makeAxis(selectedOxides[0], 0),
            baxis: makeAxis('<br>' + selectedOxides[1], 0),
            caxis: makeAxis('<br>' + selectedOxides[2], 0),
        }
    }

    function makeAxis(title, tickangle) {
        return {
            title: title,
            ticksuffix: '%',
            titlefont: {size: 20},
            tickangle: tickangle,
            tickfont: {size: 15},
            tickcolor: 'rgba(0,0,0,0)',
            ticks: 'outside',
            ticklen: 5,
            showline: true,
            showgrid: true,
        };
    }

    const config = {responsive: true};

    Plotly.newPlot('myDiv', traces, layout, config);

}

// https://plotly.com/javascript/reference/layout/ternary/
$("#ternary_plot").on('click', function () {
    if (typeof table == 'undefined') {
        showToastMessage('warning', 'Please make a SPARQL query first');
    } else if (table.rows().count() === 0) {
        showToastMessage('warning', 'No data available in table');
    } else {
        OptionsToShowOrHide(["#propertyMenu"], ["#xaxis", "#yaxis", "#glassIdMenu", "#processParameterMenu"])

        setTernaryPlot()

        $('#propertyMenu').off('change').on('change', function () {
            setTernaryPlot();
            $("#xaxis").val(this.value);
        });
    }


});

function OptionsToShowOrHide(showList, hideList) {
    showList.forEach(function (id) {
        $(id).parent().show();
    });

    hideList.forEach(function (id) {
        $(id).parent().hide();
    });
}
