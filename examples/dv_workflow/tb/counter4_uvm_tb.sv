`timescale 1ns/1ps
`include "uvm_macros.svh"

interface counter4_if(input logic clk);
  logic rst_n = 1'b1;
  logic en = 1'b0;
  wire [3:0] count;
endinterface

package counter4_tests;
  import uvm_pkg::*;

  class counter4_test extends uvm_test;
    `uvm_component_utils(counter4_test)

    virtual counter4_if vif;
    int checks;

    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if (!uvm_config_db#(virtual counter4_if)::get(this, "", "vif", vif))
        `uvm_fatal("VIF", "Missing counter4 interface")
    endfunction

    function void check_count(logic [3:0] expected, string stage);
      if (vif.count !== expected) begin
        `uvm_error("COUNT", $sformatf("%s expected %0d, saw %0d", stage, expected, vif.count))
      end else begin
        checks++;
      end
    endfunction

    task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      #2 vif.rst_n = 1'b0;
      #1 check_count(4'd0, "reset");
      @(negedge vif.clk);
      vif.rst_n = 1'b1;
      vif.en = 1'b1;
      @(posedge vif.clk);
      #1;
`ifdef INJECT_FAILURE
      check_count(4'd7, "intentional mismatch");
`else
      check_count(4'd1, "increment");
`endif
      @(negedge vif.clk);
      vif.en = 1'b0;
      @(posedge vif.clk);
      #1 check_count(4'd1, "hold");
      if (checks == 3)
        $display("COUNTER4_UVM_PASS");
      phase.drop_objection(this);
    endtask
  endclass
endpackage

module counter4_uvm_tb;
  import uvm_pkg::*;
  import counter4_tests::*;
  logic clk = 1'b0;
  always #5 clk = ~clk;

  counter4_if bus(clk);
  counter4 dut(.clk(clk), .rst_n(bus.rst_n), .en(bus.en), .count(bus.count));

  initial begin
    uvm_config_db#(virtual counter4_if)::set(null, "uvm_test_top", "vif", bus);
    run_test("counter4_test");
  end

  initial #300 $fatal(1, "UVM simulation timed out");
endmodule
