const prefix = `# 21.10.23
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX glass: <https://glasdigi.cms.uni-jena.de/glass/>
PREFIX pmdco: <https://material-digital.de/pmdco/>
PREFIX wb: <http://wikiba.se/ontology#>
    `;
let selectedOxides = [];
let selectedProps = [];
let select;
let oxide_query;
let prop_query;
let ref;
let regex;
let oxide_num;
let prop_num;

function generate_SPARQL_code(tdbId) {

    oxide_num = selectedOxides_tmp.length;
    prop_num = selectedProps_tmp.length;

    if (tdbId === "SciGlass" || tdbId === "SciGlass_mem") { // _mem means in-memory dataset
        if (oxide_num > 0 && prop_num > 0) {
            selectedOxides = selectedOxides_tmp;
            selectedProps = selectedProps_tmp;
            let select_query = SciGlass_select(selectedOxides, selectedProps);
            return [select_query, ""];
        } else if (oxide_num > 0) {
            return ["", "Please select properties"];
        } else if (prop_num > 0) {
            return ["", "Please select oxides"];
        } else {
            return ["", "Please select oxides and properties"];
        }
    } else {
        return ["", "Query UI does not support this dataset"];
    }
}

function SciGlass_select(selectedOxides, selectedProps) {
    select = "?GlasNo";
    oxide_query = "";
    prop_query = "";
    ref = "";
    regex = "";

    for (const [index, oxide] of selectedOxides.entries()) {
        regex += `REGEX(?c, '${oxide}')` + "&&";  // remove last && using [:-2]

        // oxides to select
        select += " ?" + oxide;

        // oxides to query
        oxide_query += `
        [a glass:${oxide};
           glass:hasMaterialPropertyValue/wb:quantityAmount ?${oxide}],`;
    }

    select += " ?hasTotalMolePercent";
    regex = regex.slice(0, -2);

    for (const [index, prop] of selectedProps.entries()) {
        // properties to select
        select += " ?" + prop;

        // properties to query
        prop_query += `
        [a glass:${prop};
           glass:hasMaterialPropertyValue/wb:quantityAmount ?${prop}],`;
    }
    prop_query = prop_query.slice(0, -1); // remove last character (,)

    if ($("#ref_checkbox").is(':checked')) {
        select += " ?Reference";
        ref = "glass:hasDataResourceReference ?Reference;";
    }

    let select_query = `${prefix}
SELECT ${select} WHERE {
?sciglass rdf:type glass:Glass;
glass:generatedObjectIdentifier ?identifier;
${ref}
glass:hasTotalMolePercent ?hasTotalMolePercent;
glass:hasGlassComponent ?c;
glass:hasNumberOfComponent ?n;

# Selected oxides ((Mole Percent)) & properties to query
glass:hasMaterialProperty
    ${oxide_query}
    ${prop_query}.
        
FILTER(?n = '${oxide_num}')
FILTER (${regex})

# Split ?identifier (i.e. sciglass_{Kod}_{GlasNo}_{RefID}) using "_" and bind the GlasNo part to ?GlasNo
BIND (STRBEFORE(STRAFTER(STRAFTER(?identifier, "_"), "_"), "_") AS ?GlasNo)
}
                `;
    console.debug("query:\n" + select_query)
    return select_query
}
