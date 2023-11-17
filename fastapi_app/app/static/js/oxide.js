const NABS = ['SiO2', 'Al2O3', 'B2O3', 'Na2O']
const NBS = ['SiO2', 'B2O3', 'Na2O']
const NCS = ['SiO2', 'CaO', 'Na2O']

let selectedOxides_tmp = [];

const radioButtons = $("input[type=radio][name=OxideRadioOptions]");


// Attach a click event handler to the radio buttons.
radioButtons.click(function() {
  let selectedRadioValue = $(this).val();


  // Check the corresponding checkBoxes based on the selected radio button value
  if (selectedRadioValue === "glass_system_NABS") {
    $("#checkbox_SiO2, #checkbox_Al2O3, #checkbox_B2O3, #checkbox_Na2O").prop('checked', true);
    selectedOxides_tmp = NABS;
  } else if (selectedRadioValue === "glass_system_NBS") {
    $("#checkbox_SiO2, #checkbox_B2O3, #checkbox_Na2O").prop('checked', true);
    selectedOxides_tmp = NBS;
  } else if (selectedRadioValue === "glass_system_NCS") {
    $("#checkbox_SiO2, #checkbox_CaO, #checkbox_Na2O").prop('checked', true);
    selectedOxides_tmp = NCS;
  }
  console.log("selected system: " + JSON.stringify(selectedOxides_tmp))
});


