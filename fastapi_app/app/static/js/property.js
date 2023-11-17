// see https://github.com/daweilv/treejs for how to load data to the tree.js
let selectedProps_tmp = [];
const treeData = [];
let parentId = 0;
const tree = document.getElementById('propertyTreeView');

if (tree && json_file) {
    for (const key in json_file) {
        const parent = {
            id: parentId.toString(),
            text: key,
            children: []
        };

        for (const childKey in json_file[key]) {
            const child = json_file[key][childKey];
            const childText = `${child.display_name} (${child.unit})`;
            parent.children.push({id: childKey, text: childText});
        }

        treeData.push(parent);
        parentId++;
    }
    const propTree = new Tree('#propertyTreeView', {
        // data: [{ id: '-1', text: 'root', children: data }],
        // closeDepth: 3,
        data: treeData,
        loaded: function () {

            this.selectedNodes

        },
        onChange: function () {
            // console.debug("onChange values:\n" + JSON.stringify(this.values));
            selectedProps_tmp = this.values;
        }
    });

    console.debug("Tree loaded")
}


