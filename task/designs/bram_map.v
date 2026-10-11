module ram512x40(
  input CLK1,
  input B1EN,   // read enable: accepted, not implemented (spram has no read enable;
                //   during a write the output shows old data instead of holding)
  input [0:8] A1ADDR,
  input [0:39] A1DATA,
  input A1EN,
  input [0:8] B1ADDR,
  output [0:39] B1DATA
);
  // Initial contents (ROMs). Accepted so initialized memories map; VPR ignores contents.
  parameter [20479:0] INIT = 20480'bx;

	wire [8:0] addr1_in = (A1EN == 1'b1) ? A1ADDR : B1ADDR;

	generate
		spram512x40 #() _TECHMAP_REPLACE_ (
			.clk		(CLK1),
			.addr		(addr1_in),
			.datain		(A1DATA),
			.dataout	(B1DATA),
			.we 		(A1EN));

	endgenerate

endmodule

module ram1024x20(
  input CLK1,
  input B1EN,   // read enable: accepted, not implemented (spram has no read enable;
                //   during a write the output shows old data instead of holding)
  input [0:9] A1ADDR,
  input [0:9] B1ADDR,
  input [0:19] A1DATA,
  input A1EN,
  output [0:19] B1DATA
);
  // Initial contents (ROMs). Accepted so initialized memories map; VPR ignores contents.
  parameter [20479:0] INIT = 20480'bx;

	wire [9:0] addr1_in = (A1EN == 1'b1) ? A1ADDR : B1ADDR;

	generate
		spram1024x20 #() _TECHMAP_REPLACE_ (
			.clk		(CLK1),
			.addr		(addr1_in),
			.datain		(A1DATA),
			.dataout	(B1DATA),
			.we 		(A1EN));

	endgenerate


endmodule

module ram2048x10(
  input CLK1,
  input B1EN,   // read enable: accepted, not implemented (spram has no read enable;
                //   during a write the output shows old data instead of holding)
  input [0:10] A1ADDR,
  input [0:10] B1ADDR,
  input [0:9] A1DATA,
  input A1EN,
  output [0:9] B1DATA
);
  // Initial contents (ROMs). Accepted so initialized memories map; VPR ignores contents.
  parameter [20479:0] INIT = 20480'bx;

	wire [10:0] addr1_in = (A1EN == 1'b1) ?  A1ADDR : B1ADDR;

	generate
		spram2048x10 #() _TECHMAP_REPLACE_ (
			.clk		(CLK1),
			.addr		(addr1_in),
			.datain		(A1DATA),
			.dataout	(B1DATA),
			.we 		(A1EN));

	endgenerate


endmodule




// module dpram1024x20(
// 	output[39:0] B1DATA,
// 	input CLK1,
// 	input[9:0] B1ADDR,
// 	input[9:0] A1ADDR,
// 	input[39:0] A1DATA,
// 	input A1EN,
// 	input B1EN );

// 	wire [10:0] addr1_in = {1'b0, A1ADDR};
// 	wire [10:0] addr2_in = {1'b0, B1ADDR};

// 	generate
// 		spram #() _TECHMAP_REPLACE_ (
// 			.clk		(CLK1),
// 			.addr1		(addr1_in),
// 			.addr2		(addr2_in),
// 			.din		( A1DATA),
// 			.dout		( B1DATA),
// 			.we1 		(A1EN),
// 			.we2 		(B1EN),
// 			.mode		(4'b0011) );

// 	endgenerate

// endmodule

// module dpram2048x10(
// 	output[19:0] B1DATA,
// 	input CLK1,
// 	input[10:0] B1ADDR,
// 	input[10:0] A1ADDR,
// 	input[19:0] A1DATA,
// 	input A1EN,
// 	input B1EN );

// 	wire [39:0] din_in = {20'b0, A1DATA};

// 	wire [39:0] dout_out;
// 	generate
// 		spram #() _TECHMAP_REPLACE_ (
// 			.clk		(CLK1),
// 			.addr1		(A1ADDR),
// 			.addr2		(B1ADDR),
// 			.din		({20'b0, A1DATA}),
// 			.dout		(dout_out),
// 			.we1 		(A1EN),
// 			.we2 		(B1EN),
// 			.mode		(4'b0100) );

// 	endgenerate

// 	assign B1DATA = dout_out[9:0];

// endmodule
