// SPDX-License-Identifier: MIT
// Copyright (C) 2026 Leonardo Capossio - bard0 design
// Author: Leonardo Capossio - bard0 design - hello@bard0.com
// Layer 2b property harness for `counter`: the counter contract stated once,
// checkable against ANY translation of it.
//
//   1. reset dominates:             rst        -> next count == 0
//   2. enable counts by one:        en & !rst  -> next count == count + 1
//   3. otherwise hold:             !en & !rst  -> next count == count
//
// A harness wraps the DUT instead of editing assertions into it, so the RTL
// under proof is the shipped RTL. Point the manifest's `<side>_top` at this
// module (Yosys has no SystemVerilog `bind` outside the Verific frontend, so a
// wrapper is the portable way to attach properties to unmodified RTL).
//
// `counter_bad.v` (+2 instead of +1) violates property 2 - the self-test asserts
// that this layer catches it.
module counter_props #(
    parameter WIDTH = 8
) (
    input  wire clk,
    input  wire rst,
    input  wire en
);
    wire [WIDTH-1:0] count;

    counter #(.WIDTH(WIDTH)) dut (
        .clk   (clk),
        .rst   (rst),
        .en    (en),
        .count (count)
    );

    // $past is undefined before the first clock edge; gate every property on a
    // "we have seen an edge" flag so cycle 0 cannot produce a bogus failure.
    reg past_valid = 1'b0;
    always @(posedge clk) past_valid <= 1'b1;

    always @(posedge clk) begin
        if (past_valid) begin
            if ($past(rst))
                assert (count == {WIDTH{1'b0}});
            else if ($past(en))
                assert (count == $past(count) + 1'b1);
            else
                assert (count == $past(count));
        end
    end
endmodule
